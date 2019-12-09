#!/bin/bash

# clean up
docker stop review-psql
docker rm review-psql
docker rm review_app
docker network rm review-net

# create image
docker build -t recommender_main .
# create network
docker network create review-net
# database
docker run --name review-psql --network=review-net -e POSTGRES_PASSWORD=pass -p 5432:5432 -d postgres
# start project
docker run --name review_app --network=review-net recommender_main

