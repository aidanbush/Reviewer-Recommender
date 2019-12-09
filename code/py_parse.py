#!/bin/python3.8
import ast
import pg8000
import pydriller
import os
from github import Github
from git import Repo
import json

REPOS_DIR = "repos/"
RESULT_DIR = "res/"

MODIFIED_STR = "modified"
RELATED_STR = "related"
API_STR = "api"

metrics_in_use = [MODIFIED_STR, RELATED_STR, API_STR]

def trim_filename(filename):
    return filename[:-3]

def check_overlap(start1, end1, start2, end2):
    return len(range(max([start1, start2]), min([end1, end2]) + 1))

class Visitor(ast.NodeVisitor):
    def __init__(self, filepath, filename, conn, lines, old_filepath, old_filename):
        self.filename = filename
        self.filepath = filepath
        self.conn = conn
        self.import_name = trim_filename(filename)
        self.import_mappings = {}
        self.lines = lines
        self.old_filepath = old_filepath
        self.old_filename = old_filename
        return

    def check_lines_overlap(self, start_lineno, end_lineno):
        for pair in self.lines:
            start = pair[0]
            end = pair[1]

            if check_overlap(start, end, start_lineno, end_lineno) != 0:
                return True

        return False

    def clean_import_names(self, name):
        return name.split(".")[-1]

    def add_import_mapping(self, asname, name):
        if name == None:
            name = asname
        self.import_mappings[self.clean_import_names(asname)] = self.clean_import_names(name)

    def visit_Import(self, node):
        for name in node.names:
            if name.asname is not None:
                self.add_import_mapping(name.asname, name.name)
            else:
                self.add_import_mapping(name.name, name.name)

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for name in node.names:
            if name.asname is not None:
                self.add_import_mapping(name.asname, node.module)
            else:
                self.add_import_mapping(name.name, node.module)

        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # check lines
        if len(self.lines) == 0:
            c = self.conn.cursor()
            c.execute("INSERT INTO functions (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                    (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
            self.conn.commit()
            c.close()
        elif self.check_lines_overlap(node.lineno, node.end_lineno):
            c = self.conn.cursor()
            c.execute("INSERT INTO modified_funcs (filename, filepath, name) VALUES (%s, %s, %s)",
                    (self.old_filename, self.old_filepath, node.name))
            self.conn.commit()
            c.close()

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        # check lines
        if len(self.lines) == 0:
            c = self.conn.cursor()
            c.execute("INSERT INTO functions (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                    (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
            self.conn.commit()
            c.close()
        elif self.check_lines_overlap(node.lineno, node.end_lineno):
            c = self.conn.cursor()
            c.execute("INSERT INTO modified_funcs (filename, filepath, name) VALUES (%s, %s, %s)",
                    (self.old_filename, self.old_filepath, node.name))
            self.conn.commit()
            c.close()

        self.generic_visit(node)

    def visit_Call(self, node):
        # check lines
        base = None

        if hasattr(node.func, "id"):
            func_name = node.func.id
        else:
            a = node.func
            count = 0
            while not hasattr(a, "attr"):
                if not hasattr(a, "func") or count >= 10:
                    self.generic_visit(node)
                    return
                a = a.func
                count += 1
            func_name = a.attr

            a = node.func
            count = 0
            while(type(a) == ast.Attribute):
                if count >= 10:
                    self.generic_visit(node)
                    return
                a = a.value
                count += 1
            if type(a) == ast.Name:
                base = a.id

        if base == None or base == "self":
            base = self.import_name

        if base in self.import_mappings:
            base = self.import_mappings[base]

        # add to db

        if len(self.lines) == 0:
            c = self.conn.cursor()
            c.execute("INSERT INTO func_call (filename, filepath, base_name, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s, %s)",
                    (self.filename, self.filepath, base, func_name, node.lineno, node.end_lineno))
            self.conn.commit()
            c.close()
        elif self.check_lines_overlap(node.lineno, node.end_lineno):
            c = self.conn.cursor()
            c.execute("INSERT INTO modified_func_calls (base_name, name, counts) VALUES (%s, %s, %s)"
                    + "ON CONFLICT (base_name, name) DO UPDATE SET counts = modified_func_calls.counts + (%s)",
                    (base, func_name, 1, 1, ))
            self.conn.commit()
            c.close()

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        # check lines
        # add to db

        if len(self.lines) == 0:
            c = self.conn.cursor()
            c.execute("INSERT INTO classes (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                    (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
            self.conn.commit()
            c.close()
        else:
            if self.check_lines_overlap(node.lineno, node.end_lineno):
                c = self.conn.cursor()
                c.execute("INSERT INTO modified_classes (filename, filepath, name) VALUES (%s, %s, %s)",
                        (self.old_filename, self.old_filepath, node.name))
                self.conn.commit()
                c.close()

        self.generic_visit(node)

def process_file(filepath, repopath, filename, conn, lines, old_repopath, old_filename):
    if not os.path.isfile(filepath):
        print("file", filepath, "does not exist")
        return

    if not filepath.endswith(".py"):
        return

    print("processing", filepath)

    f = open(filepath)

    a = ast.parse(f.read(), filename=filename)

    f.close()

    visitor = Visitor(repopath, filename, conn, lines, old_repopath, old_filename)

    visitor.visit(a)

def find_inner_func(conn, filename, start_line, end_line):
    # results may be greater than one if multiple files have the same name

    c = conn.cursor()
    rows = c.execute("SELECT * FROM functions where filename = (%s) and start_line <= (%s) and end_line >= (%s)",
            (filename, start_line, end_line, ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    return results

def find_func(conn, base_name, func_name):
    filename = base_name + ".py"

    c = conn.cursor()
    rows = c.execute("SELECT * FROM functions where filename = (%s) and name = (%s)",
            (filename, func_name, ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    return results

def handle_related_funcs(conn):
    # map func calls to functions
    c = conn.cursor()
    rows = c.execute("SELECT * FROM func_call",)
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    for res in results:
        # Threat to validity dont properly check which file the functions are apart of if both files have the same name and func name
        # Threat to validity dont handle functions that are part of a class differenty from a class

        # find func it is in
        callers = find_inner_func(conn, res["filename"], res["start_line"], res["end_line"])

        # find func location
        funcs = find_func(conn, res["base_name"], res["name"])

        # if funcs and callers exist match in related_funcs
        if len(callers) > 0 and len(funcs) > 0:
            # combine
            for caller in callers:
                for func in funcs:
                    c = conn.cursor()
                    c.execute("INSERT INTO related_funcs (caller_id, called_id) VALUES (%s, %s)",
                            (caller["id"], func["id"], ))
                    conn.commit()
                    c.close()

def get_author_file_ownership(file_obj, branch, repo):
    # check if file exists
    if not os.path.isfile(file_obj["path"]):
        return {}
    # blame file if blame fails the file is not in the commit
    try:
        lines = repo.repo.blame(branch, file_obj["repopath"])
    except:
        return {}

    author_lines = {}
    cur_line = 1

    last_author = None

    # process lines
    for commit, line in lines:
        email = commit.author.email
        if commit.author.email not in author_lines:
            author_lines[email] = []

        if email == last_author:
            author_lines[email][-1] = (author_lines[email][-1][0], cur_line + len(line) - 1)
        else:
            author_lines[email].append((cur_line, cur_line + len(line) - 1))

        last_author = email
        cur_line += len(line)

    return author_lines

def insert_author_lines(repopath, author_lines, conn):
    for author, lines in author_lines.items():
        for pair in lines:
            # insert into db
            c = conn.cursor()
            c.execute("INSERT INTO contributor_ownership (contributor, filepath, start_line, end_line) VALUES (%s, %s, %s, %s)",
                    (author, repopath, pair[0], pair[1], ))
            conn.commit()
            c.close()

def assign_file_ownership(file_obj, conn, author_lines):
    owned_lines = {}

    for email, pairs in author_lines.items():
        owned_lines[email] = 0
        for pair in pairs:
            owned_lines[email] += pair[1] - pair[0] + 1

    size = sum(s for s in owned_lines.values())

    for email, num_lines in owned_lines.items():
        c = conn.cursor()
        c.execute("INSERT INTO file_ownership (contributor, file_path, ownership) VALUES (%s, %s, %s)",
                (email, file_obj["repopath"], num_lines/size, ))
        conn.commit()
        c.close()

def author_ownership(start, end, author_lines):
    ownership = {author: 0 for author in author_lines.keys()}

    for author, lines in author_lines.items():
        for pair in lines:
            ownership[author] += check_overlap(pair[0], pair[1], start, end)

    return ownership

def assign_func_ownership(db_func, conn, author_lines):
    ownership = author_ownership(db_func["start_line"], db_func["end_line"], author_lines)

    size = db_func["end_line"] - db_func["start_line"] + 1

    for author, num_lines in ownership.items():
        if num_lines != 0:
            c = conn.cursor()
            c.execute("INSERT INTO func_ownership (contributor, func_id, ownership) VALUES (%s, %s, %s)",
                    (author, db_func["id"], num_lines/size, ))
            conn.commit()
            c.close()

def assign_file_funcs_ownership(file_obj, conn, author_lines):
    # get all funcs
    c = conn.cursor()
    rows = c.execute("SELECT * FROM functions where filepath = (%s)", (file_obj["repopath"], ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    # for each func assign ownership
    for func in results:
        assign_func_ownership(func, conn, author_lines)

def assign_class_ownership(db_class, conn, author_lines):
    ownership = author_ownership(db_class["start_line"], db_class["end_line"], author_lines)

    size = db_class["end_line"] - db_class["start_line"] + 1

    for author, num_lines in ownership.items():
        if num_lines != 0:
            c = conn.cursor()
            c.execute("INSERT INTO class_ownership (contributor, class_id, ownership) VALUES (%s, %s, %s)",
                    (author, db_class["id"], num_lines/size, ))
            conn.commit()
            c.close()

def assign_file_class_ownership(file_obj, conn, author_lines):
    # get all classes
    c = conn.cursor()
    rows = c.execute("SELECT * FROM classes where filepath = (%s)", (file_obj["repopath"], ))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    # for each class assign ownership
    for c in results:
        assign_class_ownership(c, conn, author_lines)

def assign_api_ownership(db_func_call, conn, author_lines):
    ownership = author_ownership(db_func_call["start_line"], db_func_call["end_line"], author_lines)

    for author, num_lines in ownership.items():
        if num_lines != 0:
            c = conn.cursor()
            # upsert
            c.execute("INSERT INTO api_ownership (contributor, base, name, counts) VALUES (%s, %s, %s, %s)"
                    + "ON CONFLICT (contributor, base, name) DO UPDATE SET counts = api_ownership.counts + (%s)",
                    (author, db_func_call["base_name"], db_func_call["name"], 1, 1, ))
            conn.commit()
            c.close()

def assign_file_api_ownership(file_obj, conn, author_lines):
    # threat std lib functions appear to be file specific
    c = conn.cursor()
    rows = c.execute("SELECT * FROM func_call WHERE filepath = (%s)",
            (file_obj["repopath"],))
    keys = [k[0].decode('ascii') for k in c.description]
    results = [dict(zip(keys, row)) for row in rows]
    c.close()

    # for each func assign ownership
    for c in results:
        assign_api_ownership(c, conn, author_lines)

def assign_ownership(file_obj, branch, repo, conn):
    author_lines = get_author_file_ownership(file_obj, branch, repo)
    if author_lines == {}:
        return
    # done so we can use it later
    insert_author_lines(file_obj["repopath"], author_lines, conn)

    # file ownership
    assign_file_ownership(file_obj, conn, author_lines)
    # func ownership
    assign_file_funcs_ownership(file_obj, conn, author_lines)
    # class ownership
    assign_file_class_ownership(file_obj, conn, author_lines)
    # api ownership
    assign_file_api_ownership(file_obj, conn, author_lines)

def get_repo_files(repo):
    path_len = len(str(repo.path))
    return [{"path": f, "repopath": f[path_len + 1: ], "name": os.path.basename(f[path_len + 1: ])}
            for f in repo.files()]

def change_repo_commit(repo, commit):
    #repo.repo.git.checkout("master")
    repo.repo.git.checkout(commit)
    # get branch and return

def parse_repo(repo, conn, commit):
    change_repo_commit(repo, commit)

    files = get_repo_files(repo)

    num_files = len(files)

    # parse python files
    i = 1
    for f in files:
        print("file", i, "out of", num_files)
        process_file(f["path"], f["repopath"], f["name"], conn, [], f["path"], f["name"])
        i += 1

    print("handling related functions")
    handle_related_funcs(conn)

    # assign ownership
    print("assigning file ownership")
    i = 1
    for f in files:
        print("file", i, "of", num_files, f)
        assign_ownership(f, 'master', repo, conn)
        i += 1

def get_contributors(conn):
    c = conn.cursor()
    rows = c.execute("SELECT DISTINCT contributor FROM contributor_ownership", ())
    results = {row[0]:{"affected":0, "related":0, "API":0} for row in rows}
    c.close()

    return results

def get_change_lines(line):
    split_line = line.split(' ')[2].split(',')

    start_lineno = int(split_line[0][1:])
    if (len(split_line) > 1):
        end_lineno = start_lineno + int(split_line[1])
    else:
        end_lineno = start_lineno

    return start_lineno, end_lineno

def get_changes(repo, conn, diff_commit, repo_path):
    # go to PR commit

    lines = repo.git().diff(diff_commit).split('\n')

    files = {}

    path_name = ''
    base_name = ''
    old_path = ''
    old_base = ''

    # search through for lines starting with "diff --git"
    for l in lines:
        if l.startswith("diff --git"):
            # extract first and second file names from there
            path_name = l.split()[-1][2:]
            base_name = os.path.basename(path_name)
            old_path = l.split()[2][2:]
            old_base = os.path.basename(path_name)
            files[(path_name, base_name, old_path, old_base)] = []
        elif l.startswith("@@"):
            # search for @@ modified lines and add to list
            # second set of ranges
            start_lineno, end_lineno = get_change_lines(l)
            files[(path_name, base_name, old_path, old_base)].append((start_lineno, end_lineno))

    # parse files
    print("parsing changed files")
    for name, lines in files.items():
        filepath = name[0]
        filename = name[1]
        old_filepath = name[2]
        old_filename = name[3]
        print("parsing file", old_filepath)

        if old_filepath == '' or old_filename == '':
            continue

        source_filepath = repo_path + '/' + filepath
        # parse file
        process_file(source_filepath, filepath, filename, conn, lines, old_filepath, old_filename)

        # add file
        c = conn.cursor()
        c.execute("INSERT INTO modified_files (filepath) VALUES (%s)",
                (old_filepath, ))
        conn.commit()
        c.close()

def modified_code_rank(conn):
    # funcs
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(ownership) AS score "
            + "FROM modified_funcs AS mf, "
                + "(SELECT contributor, fs.filepath, fs.name, fo.ownership "
                + "FROM func_ownership AS fo, functions AS fs WHERE fo.func_id = fs.id) AS f "
            + "WHERE mf.name = f.name AND mf.filepath = f.filepath GROUP BY f.contributor ",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    funcs = [dict(zip(keys, row)) for row in rows]
    c.close()

    # classes
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(ownership) AS score "
            + "FROM modified_classes AS mc, "
                + "(SELECT contributor, cs.filepath, cs.name, co.ownership "
                + "FROM class_ownership AS co, classes as cs WHERE co.class_id = cs.id) AS c "
            + "WHERE mc.name = c.name and mc.filepath = c.filepath GROUP BY c.contributor ",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    classes = [dict(zip(keys, row)) for row in rows]
    c.close()

    # files
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(ownership) AS score "
            + "FROM modified_files as mf, file_ownership as fo "
            + "WHERE mf.filepath = fo.file_path GROUP BY fo.contributor ",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    files = [dict(zip(keys, row)) for row in rows]
    c.close()

    contributors = {}

    # add func scores
    funcs_sum = sum(float(f["score"]) for f in funcs)
    for func in funcs:
        contributors[func["contributor"]] = float(func["score"]) / funcs_sum

    # add class scores
    classes_sum = sum(float(c["score"]) for c in classes)
    for c in classes:
        if c["contributor"] in contributors:
            contributors[c["contributor"]] += float(c["score"]) / classes_sum
        else:
            contributors[c["contributor"]] = float(c["score"]) / classes_sum

    # add file scores
    files_sum = sum(float(f["score"]) for f in files)
    for f in files:
        if f["contributor"] in contributors:
            contributors[f["contributor"]] += float(f["score"]) / files_sum
        else:
            contributors[f["contributor"]] = float(f["score"]) / files_sum

    # normalize
    for c in contributors:
        contributors[c] = contributors[c] / 3

    return contributors

def related_code_rank(conn):
    # fill modified_func_ids
    c = conn.cursor()
    c.execute("INSERT INTO modified_func_ids "
            + "(SELECT DISTINCT f.id "
                + "FROM modified_funcs AS mf, functions AS f "
                + "WHERE mf.name = f.name AND mf.filepath = f.filepath) ",
            ())
    conn.commit()
    c.close()

    # get caller funcs
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(ownership) AS score "
            + "FROM func_ownership AS fo, "
                + "(SELECT DISTINCT caller_id AS id "
                + "FROM related_funcs AS rf, modified_func_ids as mi "
                + "WHERE rf.called_id = mi.id AND rf.caller_id NOT IN "
                    + "(SELECT id from modified_func_ids)) AS fm "
                + "WHERE fo.func_id = fm.id GROUP BY contributor",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    caller_funcs = [dict(zip(keys, row)) for row in rows]
    c.close()

    # get called funcs
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(ownership) AS score "
            + "FROM func_ownership AS fo, "
                + "(SELECT DISTINCT called_id AS id "
                + "FROM related_funcs AS rf, modified_func_ids as mi "
                + "WHERE rf.caller_id = mi.id AND rf.called_id NOT IN "
                    + "(SELECT id from modified_func_ids)) AS fm "
                + "WHERE fo.func_id = fm.id GROUP BY contributor",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    called_funcs = [dict(zip(keys, row)) for row in rows]
    c.close()

    # combine
    total = sum(float(f["score"]) for f in caller_funcs) + sum(float(f["score"]) for f in called_funcs)
    contributors = {}

    for f in called_funcs:
        contributors[f["contributor"]] = float(f["score"]) / total

    for f in caller_funcs:
        if f["contributor"] in contributors:
            contributors[f["contributor"]] += float(f["score"]) / total
        else:
            contributors[f["contributor"]] = float(f["score"]) / total

    return contributors

def api_usage_rank(conn):
    # get api usage scores
    c = conn.cursor()
    rows = c.execute("SELECT contributor, SUM(score) AS score "
            + "FROM (SELECT mc.base_name, mc.name, ao.contributor, (mc.counts * ao.counts) AS score "
                + "FROM modified_func_calls AS mc, api_ownership AS ao "
                + "WHERE mc.base_name = ao.base AND mc.name = ao.name) AS scores "
            + "GROUP BY contributor",
            ())
    keys = [k[0].decode('ascii') for k in c.description]
    api_contributor_scores = [dict(zip(keys, row)) for row in rows]
    c.close()

    contributors = {}
    total = sum(float(a["score"]) for a in api_contributor_scores)

    for a in api_contributor_scores:
        contributors[a["contributor"]] = float(a["score"]) / total

    return contributors

def get_ranks(scores):
    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    ranks = {}

    current_rank = 0
    last_score = 0
    duplicates = 0

    for pair in sorted_scores:
        if pair[1] == last_score:
            duplicates += 1
        else:
            duplicates = 0
            current_rank += 1 + duplicates

        ranks[pair[0]] = current_rank

        last_score = pair[1]

    return ranks

# TODO check paper this is from
def combine_ranks(ranks):
    combined_ranks = {}

    for rank_pairs in ranks:
        for contributor, rank in rank_pairs.items():
            if contributor in combined_ranks:
                combined_ranks[contributor] += rank
            else:
                combined_ranks[contributor] = rank

    sorted_ranks = sorted(combined_ranks.items(), key=lambda kv: kv[1])

    return sorted_ranks

def rank_contributors(repo, repo_path, conn, main_commit, PR_commit):
    contributors = get_contributors(conn)

    change_repo_commit(repo, PR_commit)

    # get changes functions and classes
    print("getting changes from PR")
    get_changes(repo, conn, main_commit, repo_path)

    print("calculating ranks")
    # rank
    # modified code rank
    modified_scores = modified_code_rank(conn)
    # related code rank
    related_scores = related_code_rank(conn)
    # api usage rank
    api_scores = api_usage_rank(conn)

    # rank
    ranks = []

    if MODIFIED_STR in metrics_in_use:
        modified_ranks = get_ranks(modified_scores)
        ranks.append(modified_ranks)

    if RELATED_STR in metrics_in_use:
        related_ranks = get_ranks(related_scores)
        ranks.append(related_ranks)

    if API_STR in metrics_in_use:
        api_ranks = get_ranks(api_scores)
        ranks.append(api_ranks)

    return combine_ranks(ranks)

def clear_db(conn):
    tables = ["related_funcs", "api_ownership", "file_ownership", "class_ownership", "func_ownership",
            "contributor_ownership", "functions", "classes", "func_call" , "modified_funcs", "modified_classes",
            "modified_files", "modified_func_calls", "modified_func_ids"]

    for table in tables:
        c = conn.cursor()
        c.execute("DELETE FROM " + table, ())
        conn.commit()
        c.close()

def get_repo(repo_path):
    return pydriller.GitRepository(repo_path)

def rank_PR(repo_path, main_commit, PR_commit):
    # connect to db
    conn = pg8000.connect(user="postgres", password="pass", database="review_recomender")

    # clear db
    clear_db(conn)

    repo = get_repo(repo_path)

    print("parsing main repo")
    parse_repo(repo, conn, main_commit)

    ranks = rank_contributors(repo, repo_path, conn, main_commit, PR_commit)

    conn.close()

    repo.reset()

    return ranks

def get_github_pr_reviewers(pr):
    reviews = pr.get_reviews()
    reviewers = []

    for i in range(reviews.totalCount):
        reviewers.append(reviews[i].user.email)

    return reviewers

def get_github_pr_last_commit(pr):
    commits = pr.get_commits()

    return commits[commits.totalCount - 1].sha

def clone_repo(url, name):
    repo_path = REPOS_DIR + name
    # if repo not already cloned
    if not os.path.isdir(repo_path):
        print("cloning repo", url)
        Repo.clone_from(url, repo_path)

    return repo_path

def get_github_commits(repo, pr):
    pr_commits = pr.get_commits()
    all_commits = repo.get_commits()

    pr_commit = pr_commits[pr_commits.totalCount - 1]

    i = 0
    # find first pr commit
    while i < all_commits.totalCount:
        if all_commits[i] == pr_commit:
            break
        i += 1

    # find first non pr commit
    while i < all_commits.totalCount:
        if all_commits[i] not in pr_commits:
            break
        i += 1

    if i >= all_commits.totalCount:
        return None

    main_commit = all_commits[i]

    return main_commit.sha, pr_commit.sha

def handle_github_pr(g_repo, pr_id):
    pr = g_repo.get_pull(pr_id)

    # only do if already merged as not sure how can do it otherwise
    if not pr.merged:
        # error cant compare against as dont have merge commit
        print("PR not merged", pr_id)
        return

    user = pr.user.email
    reviewers = get_github_pr_reviewers(pr)

    commits = get_github_commits(g_repo, pr)
    if commits == None:
        print("Issue finding commits", pr_id)
        return

    main_commit, pr_commit = commits

    if reviewers == []:
        # no ground truth to compare against
        print("no original reviewers found", pr_id)
        return

    # clone repo if not already cloned and return pydriller repo object
    repo_path = clone_repo(g_repo.clone_url, g_repo.name)

    print("ranking PR", pr_commit)
    ranks = rank_PR(repo_path, main_commit, pr_commit)

    return ranks, reviewers

def write_results(repo_name, pr_id, recomend_ranks, correct_reviewers, test_name):
    result_filename = RESULT_DIR + test_name + "_" + os.path.basename(repo_name) + str(pr_id)

    # if results dir does not exist create it
    if not os.path.isdir(RESULT_DIR):
        os.mkdir(RESULT_DIR)

    f = open(result_filename, "w")

    json.dump({"recomended":recomend_ranks, "correct":correct_reviewers}, f)
    print(json.dumps({"recomended":recomend_ranks, "correct":correct_reviewers}))

    f.close

def test_github_repo(repo_full_name, pr_list, test_name):
    github_access = get_github_access()

    g_repo = github_access.get_repo(repo_full_name)

    print("testing repo", repo_full_name)

    for pr_data in pr_list:
        github_access = get_github_access()
        pr_id = pr_data[0]
        print("testing pr", pr_id)
        ranks = handle_github_pr(g_repo, pr_id)
        if ranks == None:
            print("pr", pr_id, "failed")
            continue
        correct_reviewers = pr_data[1:]
        recomend_ranks, _ = ranks
        # write to file to analyze
        write_results(repo_full_name, pr_id, recomend_ranks, correct_reviewers, test_name)

def get_github_access():
    f = open("access_token")
    token = f.read().rstrip()
    f.close()

    return Github(token, timeout=60)

def load_repo_json():
    f = open(REPOS_DIR + "test_repos.json")
    repos = json.load(f)
    f.close()

    return repos

def test_github_repos(test_name):
    repos = load_repo_json()

    for repo in repos:
        test_github_repo(repo["name"], repo["prs"], test_name)

def main():
    #test_github_repos("all")

    metrics_in_use = [MODIFIED_STR]
    test_github_repos(MODIFIED_STR)

    metrics_in_use = [RELATED_STR]
    test_github_repos(RELATED_STR)

    metrics_in_use = [API_STR]
    test_github_repos(API_STR)

    #main_commit = "b0dae2fedc65878ef8a124aa0f878a1de7a2fcb3" # "HEAD"
    #PR_commit = "23f437f1656fff0fe89aa18ce94be2080fcab35d" # "HEAD"

    #repo_path = "test_repo"

    #ranks = rank_PR(repo_path, main_commit, PR_commit)

    #print(ranks)

main()
