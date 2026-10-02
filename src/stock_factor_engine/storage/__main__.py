import argparse

from .database import connect_database


def main() -> None:
    parser = argparse.ArgumentParser(description='Initialize or migrate the local SQLite database.')
    parser.add_argument('--database', default='data/engine.sqlite')
    args = parser.parse_args()
    connection = connect_database(args.database)
    try:
        version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        print(f'Database ready: {args.database} (schema v{version})')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
