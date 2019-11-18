#!/bin/python3.8
import ast
import pg8000
import pydriller

def trim_filename(filename):
    return filename[:-3]

class Visitor(ast.NodeVisitor):
    def __init__(self, filename, filepath, conn):
        self.filename = filename
        self.filepath = filepath
        self.conn = conn
        self.import_name = trim_filename(filename)
        self.import_mappings = {}
        return

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
        c = self.conn.cursor()
        c.execute("INSERT INTO functions (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        c = self.conn.cursor()
        c.execute("INSERT INTO functions (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_Call(self, node):
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

        c = self.conn.cursor()
        c.execute("INSERT INTO func_call (filename, filepath, base_name, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s, %s)",
                (self.filename, self.filepath, base, func_name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        # add to db

        c = self.conn.cursor()
        c.execute("INSERT INTO classes (filename, filepath, name, start_line, end_line) VALUES (%s, %s, %s, %s, %s)",
                (self.filename, self.filepath, node.name, node.lineno, node.end_lineno))
        self.conn.commit()
        c.close()

        self.generic_visit(node)

def process_file(filepath, filename, conn):
    f = open(filepath)

    a = ast.parse(f.read(), filename=filename)

    f.close()

    visitor = Visitor(filename, filepath, conn)

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
    lines = repo.repo.blame(branch, file_obj["name"])

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
                (email, file_obj["path"], num_lines/size, ))
        conn.commit()
        c.close()

def assign_ownership(file_obj, branch, repo, conn):
    author_lines = get_author_file_ownership(file_obj, branch, repo)

    # file ownership
    assign_file_ownership(file_obj, conn, author_lines)
    # func ownership
    # class ownership

def get_repo_files(repo):
    path_len = len(str(repo.path))
    return [{"path": f, "name": f[path_len + 1: ]} for f in repo.files()]

def parse_repo(repo):
    # connect to db
    conn = pg8000.connect(user="postgres", password="pass", database="review_recomender")

    repo = pydriller.GitRepository(repo)
    files = get_repo_files(repo)

    # parse python files
    for f in files:
        process_file(f["path"], f["name"], conn)

    handle_related_funcs(conn)

    # assign ownership
    for f in files:
        assign_ownership(f, 'master', repo, conn)

    conn.close()


def main():
    parse_repo("test_repo")

main()
