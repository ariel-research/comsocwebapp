# comsocwebapp

`comsocwebapp` is a Python package that can be used to easily create web applications for computational social choice problems.

A typical `comsocwebapp` application focuses on a single social choice problem, e.g. fair allocation, voting, or participatory budgeting. It has the following features:


## Admin GUI

The admin can do the following through a convenient GUI:

1. Define the setting (e.g. the set of items to allocate, the set of candidates to choose from, the set of projects and their costs).

2. Define the format of preferences (e.g. numbers, numbers with a fixed sum, rankings, approval ballots).

3. Generate invitations for sending by email to eligible participants (e.g. heirs, voters, citizens). Invitations can use a personalized link (should be sent individually to each participant; more secure), or a generalized link (can be sent through an email group; less secure, for low-stakes applications).

4. Select from a list of one or more rules, from the rules available in existing Python libraries (e.g. `fairpyx`, `abcvoting`, `pabutools`).

5. Generate dummy users, for testing and demonstrating the various rules. The dummy users' preferences are generated randomly by default, but the admin can change them. The admin can also control the random process generating their utilities (e.g. the distribution, the upper and lower bounds). Dummy users can be deleted at any time.

6. Decide whether to run the rule only with real users, only with dummy users, or both (for testing / comparison).

7. Once the rule completes execution, the admin can view both the final outcome and the complete execution log, to understand where the outcome came from.


## Participant GUI

1. Participation starts by clicking an invitation link, which can be either an individual link (with an individual code) or a generic link (e.g. sent through an email group). Then, the user must register with email and password, or using an existing account (gmail, facebook, orcid, etc.). 

2. Participant has a convenient GUI for expressing preferences, based on the ballot format determined by the admin (e.g. assigning values to items, ranking candidates, approving/disapproving projects).

3. After the admin runs the rule, the participant can view the results, together with a personalized execution log (execution log that corresponds to his own allocation/ballot), and an explanation of why the results satisfy the guaranteed fairness criteria.


## Technical details

1. The library is based on Flask and its accompanyging libraries. It should be used similarly to Flask: import, create app, run.

2. The library should include as much stuff as possible that is common to all social choice problems. Developers who use this library should do only the minimal work required to adapt the library to their specific problem.

3. The library should include examples for different applications (e.g. fair item allocation, approval-based committee voting, participatory budgeting).

