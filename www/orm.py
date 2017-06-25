#!/user/bin/env python
#_*_coding:utf-8_*_

import asyncio, logging

import aiomysql

def log(sql, args=()):
    logging.info('SQL:%s' % sql)

#创建一个全局的连接池，每个HTTP请求都从池中获得数据库连接
#连接池由全局变量__pool储存，默认编码utf8
@asyncio.coroutine
def create_pool(loop=None, **kw):
    logging.info('create database connection pool...')
    global __pool #全局变量
    __pool = yield from aiomysql.create_pool(
        loop=loop,
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
    )

#单独封装select，其他insert,update,delete一并封装，理由如下：
#使用Cursor对象执行insert，update，delete语句时，执行结果由rowcount返回影响的行数，就可以拿到执行结果。
#使用Cursor对象执行select语句时，通过featchall()可以拿到结果集。结果集是一个list，每个元素都是一个tuple，对应一行记录。
@asyncio.coroutine
def select(sql, args, size=None):
    log(sql, args)
    global __pool
    with(yield from __pool) as conn:
        cur = yield from conn.cursor(aiomysql.DictCursor)
        yield from cur.execute(sql.replace('?', '%s'), args or ())
        if size:
            rs = yield from cur.fetchmany(size)
        else:
            rs = yield from cur.fetchall()
        yield from cur.close()
        logging.info('rows returned:%s' % len(rs))
        return rs

@asyncio.coroutine
def execute(sql, args): #执行SQL命令，返回值为受影响的行数
    log(sql)
    with(yield from __pool) as conn:
        try:
            cur = yield from conn.cursor()
            yield from cur.execute(sql.replace('?', '%s'), args)
            affected = cur.rowcount
            yield from cur.close()
        except BaseException as e:
            raise
        return affected

#用于输出元类中创建sql_insert语句中的占位符
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ','.join(L)

class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):
    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)

class ModelMetaclass(type):
    '''
    利用元类改变model类实例的生成方式，将类实例（User）输入的属性（attr，方便输入）
    以一个新的组织（__mappings__，方便实用）储存，并删除原输入属性。
    '''

    def __new__(cls, name, bases, attrs): #当前准备创建的类的对象；类的名字；类继承的父类集合；类的方法集合。
        #排除Model基类本身，基类正常生成:
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        #获取table名称：
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        #获取所有的Field和主键名：
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    #找到主键：
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys(): #删除原来输入的属性
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        attrs['__mappings__'] = mappings #保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey #主键属性名
        attrs['__fields__'] = fields #除主键外的属性名
        #构造默认的SELECT,INSERT,UPDATE和DELETE语句：
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ','.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s`(%s, `%s`) value (%s)'%(tableName, ','.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields)+1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?'%(tableName, ','.join(map(lambda f:'`%s`=?'%(mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?'%(tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

class Model(dict,metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key): #直接调回内置函数，注意这里没有下划符,注意这里None的用处,是为了当user没有赋值数据时，返回None，调用于update
        return getattr(self, key, None)

    def getValueOrDefault(self, key): #第三个参数None，可以在没有返回数值时，返回None，调用于save
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        'find objects by where clause.'
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?,?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        'find number by select and where.'
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await  select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_number_']

    @classmethod
    @asyncio.coroutine
    def find(cls, pk):
        'find object by primary key.'
        rs = yield from select('%s where `%s`=?'%(cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    @asyncio.coroutine
    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = yield from execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record:affected rows:%s'%rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)