import orm, asyncio
from models import User, Blog, Comment

async def test(loop):

    await orm.create_pool(loop=loop, user='www-data', password='www-data', db='awesome')
    u = User(name='test', email='test@example.com', passwd='0987654321', image='about:blank')
    await u.save()

loop = asyncio.get_event_loop()
loop.run_until_complete(test(loop))
loop.close()