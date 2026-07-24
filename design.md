Design Document for `comsocwebapp`
==================================


# Version 1

## Overview
`comsocwebapp` is a Python package designed to easily create web applications for computational social choice problems. A typical application focuses on a single social choice problem—such as fair allocation, voting, or participatory budgeting. 

## Admin GUI

The administrator dashboard provides a comprehensive GUI for configuring and managing the social choice process. 

*   **Problem Definition:** The admin can define the setting, including the specific set of items to allocate, the candidates to choose from, or the projects and their associated costs. Admins can also bulk-upload these entities via CSV/JSON to handle large datasets.
*   **Preference Formats:** The admin can define the exact format of user preferences, such as numerical values, numbers with a fixed sum, rankings, or approval ballots.
*   **Invitations & Access Control:** Admins can generate email invitations for eligible participants (e.g., heirs, voters, citizens). These can be personalized links (sent individually for higher security) or generalized links (sent via email groups for lower-stakes applications). 
*   **Rule Selection:** Admins can select one or more resolution rules from integrated Python libraries like `fairpyx`, `abcvoting`, or `pabutools`.
*   **Dummy Users & Simulation:** To test and demonstrate rules, the admin can generate dummy users. While their preferences are generated randomly by default, the admin can manually modify them and control the random generation parameters, such as statistical distributions and upper/lower bounds. These dummy users can be deleted at any time.
*   **Execution Scope:** The admin has the flexibility to run the selected rule exclusively with real users, exclusively with dummy users, or a mix of both for comparison purposes.
*   **Audit & Transparency:** Once the rule completes execution, the admin can view both the final outcome and the complete execution log to fully understand how the outcome was derived.
*   **Monitoring & Deadlines:** Admins have a real-time monitoring dashboard to track participation rates and the ability to set automated deadlines that lock the system.
*   **Data Export:** Admins can export results, execution logs, and anonymized user preferences to standard formats (CSV, Excel).

---

## Participant GUI

The participant experience is designed to be intuitive, transparent, and secure.

*   **Onboarding & Authentication:** Participation begins by clicking an individual or generic invitation link. Users must then register using an email and password, or authenticate using an existing provider like Gmail, Facebook, or ORCID. If using a generalized link, the system enforces email verification to prevent double-voting.
*   **Preference Elicitation:** Participants use a convenient GUI to express their preferences based on the ballot format determined by the admin (e.g., assigning values to items, ranking candidates, or approving/disapproving projects).
*   **Results & Explainability:** After the admin runs the rule, participants can view the final results. Crucially, they are provided a personalized execution log corresponding to their specific ballot or allocation, alongside a plain-language explanation of why the results satisfy the guaranteed fairness criteria.
*   **Modification & Receipts:** Participants can edit their preferences freely up until the admin's strict deadline. Upon final submission, they receive a receipt confirming their ballot was recorded accurately.
*   **Accessibility:** The voting interface is fully responsive for mobile devices and adheres to WCAG accessibility standards.

---

## Technical Details

The library prioritizes developer experience, security, and modularity.

*   **Framework Foundation:** The library is based on Flask and its accompanying ecosystem. It is designed to be used similarly to Flask itself: developers simply import the package, create the app, and run it.
*   **Boilerplate Reduction:** The library includes as much functionality as possible that is common across all social choice problems. Developers using this library only need to do the minimal work required to adapt it to their specific problem domain.
*   **Reference Implementations:** The package will include working examples for different applications, such as fair item allocation, approval-based committee voting, and participatory budgeting.
*   **Security Standards:** Built-in middleware automatically handles Cross-Site Request Forgery (CSRF) protection, input sanitization, and rate-limiting on authentication endpoints.


# Version 2


## Admin GUI updates

1. When adding options, the number should start from 1 and be consecutive for each individual setting. 

2. There should be an option to edit options in place (e.g. edit name, description, cost, etc.)

3. Allow to view and edit the preferences of the dummy voters, as well as delete individual dummy voters.


## Participant GUI updates

1. Allow to register using an existing account of gmail, github or orcid. 



## Code structure

1. There should be a folder "adapters". The generic code from adapters.py should be in one file 'generic.py', and each library-specific code should be in its own file. Also, README.md to this folder, explaining what should be done to support new libraries.

2. There should be a wrapper function for adding a setting and its options. It should insert the required info into the settings and options table. It should be used in the examples, instead of the direct DB calls.


## Examples

1. Each example should have a PORT constant, that can be set to a value different than 5000, so that several examples can  run simultaneously on the same server.

2. Each example should have an individual configuration, that contains the database name, so that several examples can run simultaneously on the same db server.

3. Example configuration should also contain the 'templates' and 'static' folders: the developer could either use the default templates, or generate new templates and use them instead.

4. Re-running the example should create a new database only if the database does not exist; it should not drop and re-create the DB if it already exists. There should be a code comment explaining how to delete and re-create the existing database, if needed.

5. Examples should use the wrapper function from above for seeding, rather than use direct DB calls.

6. Add an example that lives in its own folder, and could be copied&pasted into a separate repository (including a simplified installation guide).


## Tests

Prepare infrastructure and instructions for stress-testing, possible using `locust`. 
The stress-test should verify that the application can support 1000 simultaneous users.

## Python version

Library should be supported on Python 3.12 onwards. Simplify the code accordingly: remove all code whose sole intention is to support older versions (e.g. no need to import annotations from future).

# Version 3

## Admin GUI

1. Remove the button "view / edit dummy voters"; show the contents of that page (preferences of dummy voters + edit and delete buttons) in the main election page, under the current "Participation" heading. 

2. After clicking "Run a rule", the page should scroll to the "Run a rule" heading. Also, the values in the "Run a rule" form should remain (not reset to their default).

3. "Execution logs" should show by default only the last log. Below that, a link "View previous logs" enables the admin to view all logs.

4. The headings and sub-headings in the election panel should be larger, for a clearer visual distinction between the subsections of that page.

5. The "rule" select box should only show rules relevant to the setting (e.g. a committee voting setting should not show fair allocation rules, and vice versa).

6. The explanation "Options are numbered ... within this setting... " is not needed. Delete it

7. In the execution logs, the elected candidates are shown via their index in the main table. They should be shown via their position in the current setting, as well as with their human-readable name and description. If it is not possible to show their position, then show only their human-readable name and description.

8. For the execution logs, look for a way use the logs produced by the various libraries, to get a more informative log. 

## Participant GUI

1. With "points" input, if there is a point limit, the participant should not be allowed to enter points with sum larger or smaller than the limit. 

2. With "points" input, there should be a button "normalize", that scales all points (keeping them integers), such that their sum equals the limit.

## Specific settings

1. In the "approval voting" and the "fair allocation" settings the cost is irrelevant, so it should not be shown near the candidates in the table or in the form. Also the budget limit should not be shown.

2. In the "participatory budgeting" and "fair allocation" settings the committee size is irrelevant. It should not be shown under "Run a rule".

