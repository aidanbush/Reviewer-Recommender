#!/bin.bash

#echo review-psql:5432:database:postgres:pass > ~/.pgpass
sleep 10
export PGPASSWORD=pass ; cat init.psql | psql -h review-psql -p 5432 -U postgres

sleep 10

python py_parse.py
python parse_results.py

