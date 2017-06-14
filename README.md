*learn webapp*
==============

# day4

- 问题：提示没有loop参数

设置loop默认参数None--不成功，不报错但是不添加用户
需要添加参数 loop=asyncio.get_event_loop()--产生event loop is closed错误
需要先关闭连接池，再关闭loop

- 问题：无法连接localhost

> grant select, insert, update, delete on awesome.* to 'www-data'@'localhost' identified by 'www-data';

> 上句话意思在 awesome 库中 在localhost主机地址添加用户 www-data 密码 www-data(identified)