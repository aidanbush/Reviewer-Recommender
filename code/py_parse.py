#!/bin/python3.8
import ast
import pg8000
import pydriller
import os

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
        # Threat to validity in how I handle imports
        return name.split(".")[-1]

    def add_import_mapping(self, asname, name):
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
            func_name = node.func.attr
            a = node.func
            while(type(a) == ast.Attribute):
                a = a.value
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
            print("func")
            print(self.lines)
            print(node.lineno, node.end_lineno)
            o = self.check_lines_overlap(node.lineno, node.end_lineno)
            print(o)
            if o:
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

        # TODO also check if in class

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
    # blame file
    lines = repo.repo.blame(branch, file_obj["repopath"])

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

def change_repo_branch_commit(repo, branch, commit):
    repo.repo.git.checkout(branch)
    repo.repo.git.checkout(commit)

def parse_repo(repo, conn, branch, commit):
    # change to commit and branch
    change_repo_branch_commit(repo, branch, commit)

    files = get_repo_files(repo)

    # parse python files
    for f in files:
        process_file(f["path"], f["repopath"], f["name"], conn, [], f["path"], f["name"])

    handle_related_funcs(conn)

    # assign ownership
    for f in files:
        assign_ownership(f, 'master', repo, conn)

def get_contributors(conn):
    c = conn.cursor()
    rows = c.execute("SELECT DISTINCT contributor FROM contributor_ownership", ())
    results = {row[0]:{"affected":0, "related":0, "API":0} for row in rows}
    c.close()

    return results

def get_changes(repo, conn, diff_commit, repo_path):
    # go to PR commit

    lines = repo.git().diff(diff_commit).split('\n')
    print(lines)

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
            start_lineno = int(l.split(' ')[2].split(',')[0][1:])
            end_lineno = start_lineno + int(l.split(' ')[2].split(',')[1])
            files[(path_name, base_name, old_path, old_base)].append((start_lineno, end_lineno))

    # parse files
    for name, lines in files.items():
        filepath = name[0]
        filename = name[1]
        old_filepath = name[2]
        old_filename = name[3]

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


def rank_contributors(repo, repo_path, conn, main_branch, main_commit, PR_branch, PR_commit):
    contributors = get_contributors(conn)

    change_repo_branch_commit(repo, PR_branch, PR_commit)

    # get changes functions and classes
    get_changes(repo, conn, main_commit, repo_path)

    # rank

def clear_db(conn):
    tables = ["related_funcs", "api_ownership", "file_ownership", "class_ownership", "func_ownership", "contributor_ownership", "functions", "classes", "func_call" , "modified_funcs", "modified_classes", "modified_files", "modified_func_calls"]

    for table in tables:
        c = conn.cursor()
        c.execute("DELETE FROM " + table, ())
        conn.commit()
        c.close()

def get_repo(repo_path):
    return pydriller.GitRepository(repo_path)

def main():
    main_branch = "master"
    main_commit = "8c1dcfd84d357d4e5e27cb4725217955aa922e48" # "HEAD"
    PR_branch = "PR"
    PR_commit = "2ea4278b463d02134844a14f078609f4cac93c93" # "HEAD"

    # connect to db
    conn = pg8000.connect(user="postgres", password="pass", database="review_recomender")

    # clear db
    clear_db(conn)

    repo_path = "test_repo"

    repo = get_repo(repo_path)

    parse_repo(repo, conn, main_branch, main_commit)

    rank_contributors(repo, repo_path, conn, main_branch, main_commit, PR_branch, PR_commit)

    repo.reset() # need?

    conn.close()

main()
