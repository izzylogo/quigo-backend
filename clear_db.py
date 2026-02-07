from database import engine
from models import Base
from sqlalchemy import MetaData

# Reflect the database schema
metadata = MetaData()
metadata.reflect(bind=engine)

# Connect and execute delete for each table
with engine.begin() as conn:
    for table in reversed(metadata.sorted_tables):
        conn.execute(table.delete())
    print("Database cleared successfully!")
