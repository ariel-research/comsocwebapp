# AI Coding Agent Prompt: Build `comsocwebapp`

**Role:** You are a Senior Backend Python Developer and Database Architect specializing in Flask.

**Task:** Build the core logic, database interactions, and backend APIs for a new Python open-source package called `comsocwebapp`. This package provides developers with a boilerplate Flask web application for solving computational social choice problems (fair allocation, voting, participatory budgeting). 

**Context & Requirements:**
I will provide two documents: `design.md` (which outlines the Admin/Participant GUI features, problem definitions, and application flow) and `database.md` (which strictly defines the database schema). 

Read them carefully and adhere to the following strict constraints:

1. **No ORMs:** You must use Python's built-in `sqlite3` or standard DB-API compliant connectors executing **raw ANSI SQL**. Do not use SQLAlchemy, Peewee, or any ORM.
2. **SQL Standards:** Ensure all SQL queries use parameterized inputs (e.g., `?` or `%s`) to prevent SQL injection. Queries must be universally compatible (avoid JSON column types, proprietary upserts, etc.). Follow the schema in `database.md` exactly, mapping boolean flags to `INTEGER` (0 or 1).
3. **App Structure:** The package should be designed to be imported and run simply. Provide an application factory function `create_app()`. 
4. **Integration Interfaces:** Create adapter functions that fetch data from the raw SQL queries and format them into generic dictionaries/lists. These adapters should easily bridge our database data into external computational libraries (specifically `fairpyx`, `abcvoting`, and `pabutools`).
5. **Core Features to Implement First:**
    *   Database initialization script (`init_db`).
    *   Authentication and invitation token generation logic.
    *   Admin logic for bulk-generating dummy users with randomized preferences.
    *   The core routing for a participant to cast a ballot (inserting into the `preferences` table).
    *   Admin route to trigger a calculation and store the result/log in `execution_logs`.
    * A comprehensive README.md that serves as the main installation and getting-started guide.    

**Output Instructions:**
*   Start by creating the directory structure layout for the package.
*   Provide the `schema.sql` file.
*   Provide the `db.py` file to handle connections and raw queries.
*   Provide the core Flask blueprints for `admin` and `participant`.
*   Provide the adapter module to bridge our SQL data to the social choice libraries.
*   Include docstrings and comments explaining how the raw SQL is structured for universal database compatibility.
*   Provide a README.md file that includes:
    * Prerequisites (e.g., Python version requirements).
    * Step-by-step instructions for setting up a virtual environment and installing dependencies.
    * The exact command for executing the database initialization script (init_db).
    * A simple command to run the Flask development server so a user can immediately view the Admin GUI.
