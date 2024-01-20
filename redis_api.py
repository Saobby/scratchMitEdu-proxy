import redis

DATABASE_HOST = "127.0.0.1"  # redis address
DATABASE_PORT = 6379  # redis port

connection_pool = redis.ConnectionPool(host=DATABASE_HOST, port=DATABASE_PORT, decode_responses=True,
                                       retry_on_timeout=5, max_connections=1024)


def get_session():
    return redis.Redis(connection_pool=connection_pool)


if __name__ == "__main__":
    pass
