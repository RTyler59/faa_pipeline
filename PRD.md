# Project Requirements Document (PRD)
## Project Name: FAA Air Operator Data Pipeline

### 1. Objective
Build an automated, robust, and ethical data pipeline that harvests air operator (airline carrier) certification data from the official FAA Air Operator 14 CFR Search portal, structures it, and stores it in a PostgreSQL database for downstream querying and analysis.

### 2. Scope & Target Environment
- **Target URL:** https://www.faa.gov/data/av-info/air-operator-far-search
- **Data Scope:** Extract 14 CFR operational parts including Part 121 (scheduled airline), 125 (large aircraft/private), 129 (foreign air carrier), 133 (rotorcraft external load), 135 (charter/air taxi) include aircraft (Make/Model/Series) in data.
- **Development Environment:** VS Code
- **Language/Runtime Stack:** Python (Recommended for scraping/data processing) or Node.js.
- **Database Engine:** PostgreSQL (Local Docker container or native instance).

### 3. Functional Requirements

#### Phase 1: Workspace & Architecture Setup
- Establish a clean, scalable directory structure distinguishing the scraping engine, database schemas, utility scripts, and configuration files.
- Configure environment variables securely (`.env`) for database credentials and execution parameters.

#### Phase 2: Database Architecture (PostgreSQL)
- Create a relational schema to cleanly handle:
  - **Air Operators:** Name, Doing Business As (DBA) names, Certificate Number, 14 CFR Part classification, and local Flight Standards District Office (FSDO) mapping.
  - **Aircraft Inventory:** Map specific aircraft Make, Model, and Series variants back to their unique parent operator record (One-to-Many relationship).
- Implement idempotent database scripts (`schema.sql` utilizing `CREATE TABLE IF NOT EXISTS`).

#### Phase 3: Web Scraping Engine & Compliance
- **Tool Assessment:** Evaluate the FAA target site infrastructure to determine whether light static parsing (e.g., Beautiful Soup) or browser automation/dynamic execution (e.g., Playwright/Selenium) is necessary to navigate the CFR parts and "Show Aircraft" toggles.
- **Ethical Safeguards & Compliance:** 
  - Read and strictly adhere to the FAA domain's `robots.txt` directives.
  - Implement programmatic throttling (adaptive delay timers between 2 to 5 seconds per request).
  - Use custom, identifying User-Agent strings.
  - Gracefully handle network timeouts, HTTP errors (429, 500), and unexpected DOM changes.
- **Ingestion Execution:** Parse the scraped DOM structures and safely upsert data into PostgreSQL using parameterized statements or an ORM to block SQL injection risks.

### 4. Code Quality & Guardrails
- **Error Handling:** All extraction actions must log telemetry events rather than catastrophically failing the script.
- **Modularity:** Keep extraction logic, database logic, and orchestrations clearly separated.