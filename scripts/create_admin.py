#!/usr/bin/env python3
"""
Create the initial admin user.
Run once after first migration: python scripts/create_admin.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.db import User
    from app.core.security import hash_password

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL env var not set")
        sys.exit(1)

    email = os.environ.get("ADMIN_EMAIL", "admin@monet.local")
    password = os.environ.get("ADMIN_PASSWORD", "changeme123")

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        async with session.begin():
            from sqlalchemy import select
            existing = await session.execute(select(User).where(User.email == email))
            if existing.scalar_one_or_none():
                print(f"Admin user {email} already exists.")
                return

            admin = User(
                email=email,
                hashed_password=hash_password(password),
                full_name="Administrator",
                role="admin",
                is_active=True,
            )
            session.add(admin)

    await engine.dispose()
    print(f"✓ Admin user created: {email}")
    print(f"  Password: {password}")
    print("  Change this password after first login!")


if __name__ == "__main__":
    asyncio.run(main())
