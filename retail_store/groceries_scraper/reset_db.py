from models import Base, engine, Category, Unit, Product, ProductSpecification
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_db():
    logger.info("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("Creating all tables from new schema...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database reset completed successfully!")

if __name__ == "__main__":
    reset_db()
