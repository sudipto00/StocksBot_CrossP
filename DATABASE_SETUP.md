# Database Setup and Migration Guide

This guide covers setting up and managing the StocksBot database.

## First-Time Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

This installs SQLAlchemy and Alembic along with other dependencies.

### 2. Run Migrations

```bash
cd backend
alembic upgrade head
```

This creates the database file (`stocksbot.db`) and all tables.

### 3. Verify Database

```bash
# Check that database file was created
ls -lh stocksbot.db

# View tables (requires sqlite3)
sqlite3 stocksbot.db ".tables"
```

You should see:
- alembic_version
- config
- orders
- positions
- strategies
- trades

## Database Configuration

### Development (Default)

By default, StocksBot uses SQLite with a local database file:

```
DATABASE_URL=sqlite:///./stocksbot.db
```

No configuration needed - it just works!

### Production (PostgreSQL)

For production, set the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/stocksbot"
```

Or create a `.env` file in the `backend/` directory:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/stocksbot
```

## Migration Workflow

### Checking Migration Status

```bash
# View current migration version
alembic current

# View migration history
alembic history

# View detailed migration info
alembic history --verbose
```

### Applying Migrations

```bash
# Upgrade to latest version
alembic upgrade head

# Upgrade by specific number of versions
alembic upgrade +1

# Upgrade to specific version
alembic upgrade <revision_id>
```

### Rolling Back Migrations

```bash
# Downgrade one version
alembic downgrade -1

# Downgrade to specific version
alembic downgrade <revision_id>

# Downgrade to base (empty database)
alembic downgrade base
```

### Creating New Migrations

When you modify the database models in `storage/models.py`:

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Review the generated migration file in alembic/versions/
# Edit if necessary

# Apply the migration
alembic upgrade head
```

**Important:** Always review auto-generated migrations before applying them!

### Creating Empty Migration

For data migrations or custom SQL:

```bash
# Create empty migration template
alembic revision -m "Description"

# Edit the generated file to add your changes
```

## Common Tasks

### Reset Database (Development Only)

```bash
cd backend

# Delete database file
rm stocksbot.db

# Recreate from migrations
alembic upgrade head
```

### Backup Database

```bash
# SQLite
cp stocksbot.db stocksbot.db.backup

# PostgreSQL
pg_dump stocksbot > backup.sql
```

### Restore Database

```bash
# SQLite
cp stocksbot.db.backup stocksbot.db

# PostgreSQL
psql stocksbot < backup.sql
```

### View Database Contents

```bash
# SQLite - Interactive shell
sqlite3 stocksbot.db

# Within sqlite3 shell:
.tables              # List tables
.schema positions    # View table schema
SELECT * FROM positions;  # Query data
.quit               # Exit

# PostgreSQL
psql stocksbot
\dt                  # List tables
\d positions         # Describe table
SELECT * FROM positions;
\q                   # Exit
```

## Troubleshooting

### Migration Conflicts

If you get migration conflicts (e.g., after pulling changes):

```bash
# Check current version
alembic current

# Check history
alembic history

# Downgrade to common ancestor
alembic downgrade <common_version>

# Upgrade to head
alembic upgrade head
```

### Can't Connect to Database

1. Check DATABASE_URL is correct
2. For PostgreSQL, ensure server is running
3. Verify credentials and database exists
4. Check network/firewall settings

### Migration Fails

1. Read the error message carefully
2. Check the migration file for issues
3. Manually fix the database if needed
4. Update migration file
5. Try again

### Database Locked (SQLite)

SQLite databases can lock during concurrent access:

1. Close all connections to the database
2. Stop the backend server
3. Wait a few seconds
4. Try again

For production with high concurrency, use PostgreSQL instead.

## Environment Variables

### DATABASE_URL
Database connection string.

- SQLite: `sqlite:///./stocksbot.db`
- PostgreSQL: `postgresql://user:pass@host:port/dbname`

### SQL_ECHO
Enable SQL query logging (useful for debugging).

```bash
export SQL_ECHO=true
```

## Best Practices

1. **Always use migrations** - Never modify the database schema directly
2. **Review auto-generated migrations** - They may not be perfect
3. **Test migrations** - Try upgrade/downgrade cycle before committing
4. **Backup before migrations** - Especially in production
5. **Use version control** - Commit migration files to git
6. **One change per migration** - Makes rollbacks easier
7. **Don't modify committed migrations** - Create new ones instead

## Production Checklist

Before deploying to production:

- [ ] Switch to PostgreSQL (or another production DB)
- [ ] Set DATABASE_URL environment variable
- [ ] Run migrations: `alembic upgrade head`
- [ ] Set up database backups
- [ ] Configure connection pooling if needed
- [ ] Test migration rollback procedure
- [ ] Monitor database performance
- [ ] Set up database access controls
- [ ] Disable SQL_ECHO (don't log queries in prod)

## Resources

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [FastAPI with Databases](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- Storage Module README: `backend/storage/README.md`
