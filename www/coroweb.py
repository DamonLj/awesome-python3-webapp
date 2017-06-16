#!/user/bin/env python
#_*_coding:utf-8_*_

import asyncio, os, inspect, logging, functools

from urllib import parse

from aiohttp import web

from apis import  APIError

#运用偏函数，一并生成GET、POST等请求方法的装饰器
def request_(path, *, methor): #下划线和*意义？
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func) #更正函数的签名
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = methor #储存方法信息
        wrapper.__route__ = path #储存路径信息
        return wrapper
    return decorator

get = functools.partial(request, methor='GET')
post = functools.partial(request, methor='POST')

def get_required_kw_args(fn): #收集没有默认值的命名关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
        return tuple(args)

def get_name_kw_args(fn): #收集命名关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
        return tuple(args)

def has_name_kw_args(fn): #判断有没有命名关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_args(fn): #判断有没有关键字参数
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

def has_request_args(fn): #判断是否含有名叫‘request’参数，且该参数是否为最后一个参数
    params = inspect.signature(fn).parameters
    sig = inspect.signature(fn)
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue #跳出当前循环，进入下一循环
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and
                      param.kind != inspect.Parameter.KEYWORD_ONLY and
                      param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function:%s%s' %
                             (fn.__name__,str(sig)))
    return found

#定义RequestHanlder
class RequestHanlder(object):

    def __init__(self, app, fn):
        self._app = app
        self._fn = fn
        self._require_kw_args = get_required_kw_args(fn)
        self._name_kw_args = get_name_kw_args(fn)
        self._has_name_kw_args = has_name_kw_args(fn)
        self._has_var_kw_args = has_var_kw_args(fn)
        self._has_request_args = has_request_args(fn)

    async def __call__(self, request): #__call__构造协程
        kw = None
        if self._has_name_kw_args or self._has_var_kw_args:
            if request.method == 'POST':
                if not request.content_type: #查询有没提交数据的格式（EncType）
                    return web.HTTPBadRequest('Missing Content_type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = await request.json() #read request body decoded as json.
                    if not isinstance(params,dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    # reads POST parameters from request body.If method is not POST, PUT, PATCH, TRACE or DELETE or
                    # content_type is not empty or application/x-www-form-urlencoded or
                    # multipart/form-data returns empty multidict.
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content_type:%s' % (request.content_type))
            if request.method == 'GET':
                qs = request.query_string() #The query string in the URL
                if qs:
                    for k, v in parse.parse_qs(qs, True).items():
                    # Parse a query string given as a string argument.Data are returned as a dictionary.
                    # The dictionary keys are the unique query variable names and
                    # the values are lists of values for each name.
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_args and self._name_kw_args:
            # 当函数参数没有关键字参数时，移去request除命名关键字参数所有的参数信息
                copy = dict()
                for name in self._name_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            for k, v in request.match_info.items(): #检查命名关键字参数
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args:%s' % k)
                kw[k] = v
        if self._has_request_args:
            kw['request'] = request
        if self._require_kw_args: #假如命名关键字参数（没有附加默认值），request没有提供相应的数值，报错
            for name in self._require_kw_args:
                if name not in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % (name))
        logging.info('call with args:%s' % str(kw))

        try:
            r = await self.func(**kw)
            return r
        except APIError as e: #APIError另外创建
            return dict(error=e.error, data=e.data, message=e.message)
        