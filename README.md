# Reviewer-Recommender

## Requirements

To run this artifact only docker and bash are required as it all runs within a docker container.

## Files

In the code directory the main project code is stored, the files include:
 - Dockerfile: Docker file used to create the docker image for the project.
 - requirements.txt: a text file of python libraries required to make the project work which is used by the Docker file.
 - init.pqsl: The database initialisation file.
 - py_parse.py: The file that implements the OK algorithm.
 - parse_results.py: The python file for processing results and generating stats.
 - repos/test_repos.json: The json file used to test against it includes all of the commits and ground truth reviewers.
 - run.sh: the script used to create and run the docker containers.
 - run_and_results.sh: a wrapper script for the python scripts.

## Running the artifact

To run the artifact you must first create a github access token (https://github.com/settings/tokens) and store it in a file named `access_token` in the `code/` directory.
The token must have the following permissions: public_repo, read:packages, read:user, repo:status, user:email.
And then simply call the run.sh bash script from within the `code` directory.

Two docker containers will be created `review_app`, `review-psql`, and a single docker network `review-net`.

It may take over an hour to run to completion.
