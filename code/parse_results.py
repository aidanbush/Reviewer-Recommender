#!/bin/python
import json
import os
import statistics as s

DIR = "res/"

def topk(recomended, correct, k):
    if k > len(recomended):
        k = len(recomended)

    for i in range(k):
        if recomended[i][0] in correct:
            return 1

    return 0

def MRR(recomended, correct):
    for i in range(len(recomended)):
        if recomended[i][0] in correct:
            return 1/(i+1)

    return 0

def stats(recomended, correct):
    top1 = topk(recomended, correct, 1)
    top5 = topk(recomended, correct, 5)
    top10 = topk(recomended, correct, 10)

    mrr = MRR(recomended, correct)

    return top1, top5, top10, mrr

def stats_on_test(test_name):
    top1s = []
    top5s = []
    top10s = []
    mrrs = []

    num_recomended = []
    top1_not_found = 0
    top5_not_found = 0
    top10_not_found = 0
    not_in_recomended = 0

    # open files
    for filename in os.listdir(DIR):
        if not filename.startswith(test_name):
            continue

        f = open(DIR + filename)
        reviews = json.load(f)
        f.close()

        recomended = reviews["recomended"]
        correct = reviews["correct"][0]

        num_recomended.append(len(recomended))

        # calculate stats
        top1, top5, top10, mrr = stats(recomended, correct)

        top1s.append(top1)
        top5s.append(top5)
        top10s.append(top10)
        mrrs.append(mrr)

        if top1 == 0:
            top1_not_found += 1
        if top5 == 0:
            top5_not_found += 1
        if top10 == 0:
            top10_not_found += 1
        if mrr == 0:
            not_in_recomended += 1

    top1mean = s.mean(top1s)
    top5mean = s.mean(top5s)
    top10mean = s.mean(top10s)
    mrrmean = s.mean(mrrs)

    print(test_name, "top1,", top1mean)
    print(test_name, "top5,", top5mean)
    print(test_name, "top10,", top10mean)
    print(test_name, "mmr,", mrrmean)

    print(test_name, "top1 not found,", top1_not_found)
    print(test_name, "top5 not found,", top5_not_found)
    print(test_name, "top10 not found,", top10_not_found)
    print(test_name, "not in recomended,", not_in_recomended)

def main():
    if not os.path.exists(DIR):
        os.makedirs(DIR)

    stats_on_test("all")
    stats_on_test("modified")
    stats_on_test("related")
    stats_on_test("api")

main()
