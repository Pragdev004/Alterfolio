from app.db.database import SessionLocal

print("Creating session...")

db = SessionLocal()

print("Session created.")

try:
    print("Getting connection...")
    conn = db.connection()
    print("Connected!")

finally:
    db.close()
    print("Closed.")