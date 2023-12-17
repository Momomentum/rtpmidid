#!/usr/bin/python3

import select
import tty
import shutil
import socket
import sys
import json
import os
import time


class Connection:
    def __init__(self, filename):
        self.filename = filename
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.connect(filename)
        except ConnectionRefusedError:
            print(
                "Connection refused to %s. Can set other location with --control=<path>"
                % filename
            )
            sys.exit(1)

    def command(self, command):
        self.socket.send(json.dumps(command).encode("utf8") + b"\n")
        data = self.socket.recv(1024 * 1024)  # load all you can. 1MB cool!
        return json.loads(data)


def maybe_int(txt: str):
    try:
        return int(txt)
    except:
        pass
    return txt


def parse_arguments(argv):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--control")
    parser.add_argument("--top", action="store_true")
    parser.add_argument("command", nargs="*")

    return parser.parse_args(argv[1:])


def parse_commands(argv):
    cmd = []
    for x in argv:
        if x == ".":
            yield {"method": cmd[0], "params": [maybe_int(x) for x in cmd[1:]]}
            cmd = []
        else:
            cmd.append(x)
    if cmd:
        yield {"method": cmd[0], "params": [maybe_int(x) for x in cmd[1:]]}


def safe_get(data, *keys):
    try:
        for key in keys:
            if key in data:
                data = data[key]
            else:
                return ""
    except:
        return ""
    return data


class Top:
    ANSI_CLEAR_SCREEN = "\033[2J\033[H"
    ANSI_PUSH_SCREEN = "\033[?1049h"
    ANSI_POP_SCREEN = "\033[?1049l"

    ANSI_TEXT_BLACK = "\033[30m"
    ANSI_TEXT_RED = "\033[31m"
    ANSI_TEXT_GREEN = "\033[32m"
    ANSI_TEXT_YELLOW = "\033[33m"
    ANSI_TEXT_BLUE = "\033[34m"
    ANSI_TEXT_PURPLE = "\033[35m"
    ANSI_TEXT_CYAN = "\033[36m"
    ANSI_TEXT_WHITE = "\033[37m"
    ANSI_TEXT_GREY = "\033[90m"
    ANSI_TEXT_BOLD = "\033[1m"

    ANSI_BG_BLACK = "\033[40m"
    ANSI_BG_RED = "\033[41m"
    ANSI_BG_GREEN = "\033[42m"
    ANSI_BG_YELLOW = "\033[43m"
    ANSI_BG_BLUE = "\033[44m"
    ANSI_BG_PURPLE = "\033[45m"
    ANSI_BG_CYAN = "\033[46m"
    ANSI_BG_WHITE = "\033[47m"
    ANSI_BG_GREY = "\033[100m"

    ANSI_RESET = "\033[0m"

    def __init__(self, conn: Connection):
        # terminal width and height from stty
        self.conn = conn
        width, height = shutil.get_terminal_size()
        self.selected_row_index = 0
        self.selected_col_index = 0
        self.selected_row = None
        self.max_rows = height - 2
        self.width = width
        self.height = height
        self.data = []

        self.COLUMNS = [
            {
                "name": "ID",
                "get": lambda data: safe_get(data, "id"),
                "width": 8,
                "align": "right",
            },
            {
                "name": "Type",
                "get": lambda data: safe_get(data, "type"),
                "width": 40,
                "align": "left",
            },
            {
                "name": "Name",
                "get": lambda data: safe_get(data, "name"),
                "width": 0,
                "align": "left",
            },
            {
                "name": "Status",
                "get": lambda data: safe_get(data, "peer", "status"),
                "width": 20,
                "align": "left",
            },
            {
                "name": "Sent",
                "get": lambda data: safe_get(data, "stats", "sent"),
                "width": 8,
                "align": "right",
            },
            {
                "name": "Received",
                "get": lambda data: safe_get(data, "stats", "recv"),
                "width": 8,
                "align": "right",
            },
            {
                "name": "Latency",
                # the unicode symbol for +- is \u00B1
                "get": self.get_latency,
                "width": 20,
                "align": "right",
            },
            {
                "name": "Send To",
                "get": lambda data: ", ".join(
                    str(x) for x in safe_get(data, "send_to")
                ),
                "width": 10,
            },
        ]

        # make Name column as wide as possible
        self.COLUMNS[2]["width"] = (
            self.width
            - sum(x["width"] for x in self.COLUMNS)
            - (1 * (len(self.COLUMNS) - 1))
        )
        self.max_cols = len(self.COLUMNS)

        # set the terminal input in one char per read
        tty.setcbreak(sys.stdin)

    def terminal_goto(self, x, y):
        print("\033[%d;%dH" % (y, x), end="")

    def get_latency(self, data):
        avg = safe_get(data, "peer", "latency_ms", "average")
        if not avg:
            return ""
        stddev = safe_get(data, "peer", "latency_ms", "stddev")
        return f"{avg}ms \u00B1 {stddev}ms"

    def print_table(self, table: list[list[str]]):
        def format_cell(cell, column):
            if column.get("align") == "right":
                return "{:>{width}}".format(cell, width=column["width"])
            else:
                return "{:{width}}".format(cell, width=column["width"])

        max_cols = self.max_cols - 1
        for rown, row in enumerate(table):
            for coln, cell in enumerate(zip(row, self.COLUMNS)):
                cell, column = cell
                print(self.get_color_cell(row, rown, coln), end="")
                print(format_cell(cell, column), end="")
                if coln != max_cols:
                    print(" ", end="")
        print(self.ANSI_RESET, end="")

    def get_color_cell(self, row: dict, rown: int, coln: int):
        if rown == 0:
            if coln == self.selected_col_index:
                return self.ANSI_BG_CYAN + self.ANSI_TEXT_WHITE + self.ANSI_TEXT_BOLD
            return self.ANSI_BG_PURPLE + self.ANSI_TEXT_WHITE + self.ANSI_TEXT_BOLD

        # we are in the table rows
        rown -= 1

        if rown == self.selected_row_index:
            return self.ANSI_BG_WHITE + self.ANSI_TEXT_BLACK

        if row[3] == "CONNECTED":
            return self.ANSI_BG_GREEN + self.ANSI_TEXT_WHITE
        elif row[3] == "CONNECTING":
            return self.ANSI_BG_YELLOW + self.ANSI_TEXT_BLACK
        elif row[3] == "":
            return self.ANSI_BG_BLACK + self.ANSI_TEXT_GREY
        else:
            return self.ANSI_BG_GREY + self.ANSI_TEXT_BLACK

    def print_header(self):
        # write a header with the rtpmidid client, version, with color until the end of line
        print(self.ANSI_BG_BLUE + self.ANSI_TEXT_BOLD + self.ANSI_TEXT_WHITE, end="")
        self.print_padding("rtpmidid-cli v23.12")
        # color until next newline
        print(self.ANSI_RESET, end="")
        print()

    def print_footer(self):
        self.terminal_goto(1, self.height)

        print(self.ANSI_BG_BLUE + self.ANSI_TEXT_BOLD + self.ANSI_TEXT_WHITE, end="")
        footer_left = f"Press Ctrl-C to exit | [q]uit | [k]ill midi peer | [c]onnect to peer | [up] [down] to navigate"
        footer_right = f"| rtpmidid-cli v23.12 | (C) Coralbits 2023"
        padding = self.width - len(footer_left) - len(footer_right)
        self.print_padding(f"{footer_left}{' ' * padding}{footer_right}")
        print(self.ANSI_RESET, end="")

    def print_padding(self, text, count=None):
        if count is None:
            count = self.width

        padchars = count - len(text)
        if padchars < 0:
            padchars = 0
        print(text[:count] + " " * padchars, end="")

    def wait_for_input(self, timeout=1):
        start = time.time()
        while True:
            if time.time() - start > timeout:
                return
            if sys.stdin in select.select([sys.stdin], [], [], 1)[0]:
                # read a key
                key = sys.stdin.read(1)
                # if key is the ansi code for arrow keys, read the next 2 bytes and return "up", "down", "left", "right"
                if key == "\033":
                    key += sys.stdin.read(2)
                    if key == "\033[A":
                        return "up"
                    elif key == "\033[B":
                        return "down"
                    elif key == "\033[C":
                        return "right"
                    elif key == "\033[D":
                        return "left"
                return key

    def parse_key(self, key):
        # up got up in the current row
        if key == "up":
            self.selected_row_index -= 1
            if self.selected_row_index < 0:
                self.selected_row_index = 0
        elif key == "down":
            self.selected_row_index += 1
            if self.selected_row_index >= self.max_rows:
                self.selected_row_index = self.max_rows - 1
        if key == "left":
            self.selected_col_index -= 1
            if self.selected_col_index < 0:
                self.selected_col_index = self.max_cols - 1
        elif key == "right":
            self.selected_col_index += 1
            if self.selected_col_index >= self.max_cols:
                self.selected_col_index = 0
        elif key == "q":
            sys.exit(0)
        elif key == "k":
            self.conn.command(
                {"method": "router.remove", "params": [self.selected_row["id"]]}
            )
        elif key == "c":
            peer_id = self.dialog_ask("Connect to which peer id?")
            self.conn.command(
                {
                    "method": "router.connect",
                    "params": {"from": self.selected_row["id"], "to": int(peer_id)},
                }
            )

    def set_cursor(self, x, y):
        print("\033[%d;%dH" % (y, x), end="")

    def dialog_ask(self, question, width=60):
        # print a blue box with white text
        width_2 = width // 2
        start_x = self.width // 2 - width_2
        start_y = self.height // 3

        print(self.ANSI_BG_BLUE + self.ANSI_TEXT_WHITE + self.ANSI_TEXT_BOLD, end="")
        self.terminal_goto(start_x, start_y)
        self.print_padding("", width_2)
        self.terminal_goto(start_x, start_y + 1)
        self.print_padding(" " + question, width_2)
        self.terminal_goto(start_x, start_y + 2)
        self.print_padding("", width_2)
        self.terminal_goto(start_x, start_y + 4)
        self.print_padding("", width_2)
        print(self.ANSI_RESET + self.ANSI_BG_WHITE + self.ANSI_TEXT_BLUE, end="")
        self.terminal_goto(start_x, start_y + 3)
        self.print_padding("", width_2)
        self.set_cursor(start_x + 1, start_y + 3)

        sys.stdout.flush()
        answer = ""
        while True:
            key = self.wait_for_input()
            if key == "\n":
                break
            elif key == "\x7f":
                answer = answer[:-1]
            elif key:
                answer += key
            self.terminal_goto(start_x, start_y + 3)
            self.print_padding(" " + answer, width_2)
            self.set_cursor(start_x + 1 + len(answer), start_y + 3)
            sys.stdout.flush()
        print(self.ANSI_RESET, end="")

        return answer

    def print_row(self, row):
        if not row:
            return

        text = json.dumps(row, indent=2)

        data_rows = len(self.data)
        top_area = data_rows + 4
        max_col = self.height - top_area - 5

        print(self.ANSI_BG_BLUE + self.ANSI_TEXT_WHITE, end="")
        self.print_padding(f"Current Row {self.height}: ")
        print(self.ANSI_RESET, end="")
        width_2 = self.width // 2
        for idx, row in enumerate(text.split("\n")):
            if idx >= max_col:
                self.terminal_goto(width_2, top_area + idx - max_col)
            else:
                self.terminal_goto(0, top_area + idx)
            print(row)

    def print_data(self):
        data = self.conn.command({"method": "status"})
        peers = data["result"]["router"]
        self.data = peers
        self.max_rows = len(peers)
        if self.selected_row_index >= self.max_rows:
            self.selected_row_index = self.max_rows - 1
        self.selected_row = peers[self.selected_row_index]

        table = [[x["name"] for x in self.COLUMNS]]
        data = [[x["get"](peer) for x in self.COLUMNS] for peer in peers]

        data.sort(
            key=lambda x: "ZZZZZZZ"
            if not x[self.selected_col_index]
            else str(x[self.selected_col_index])
        )

        table.extend(data)
        self.print_table(table)

    def top_loop(self):
        print(self.ANSI_PUSH_SCREEN, end="")
        try:
            while True:
                print(self.ANSI_CLEAR_SCREEN, end="")
                self.print_header()
                self.print_data()
                self.print_row(self.selected_row)
                self.print_footer()
                print(flush=True, end="")
                key = self.wait_for_input()
                if key:
                    self.parse_key(key)
        except KeyboardInterrupt:
            pass
        finally:
            print(self.ANSI_POP_SCREEN, end="")


def main(argv):
    settings = parse_arguments(argv)
    if settings.control:
        socketpath = settings.control
    else:
        socketpath = "/var/run/rtpmidid/control.sock"

    if not os.path.exists(socketpath):
        print("Control socket %s does not exist" % socketpath)
        sys.exit(1)

    try:
        conn = Connection(socketpath)
    except Exception as e:
        print(str(e))
        sys.exit(1)

    if settings.top:
        return Top(conn).top_loop()

    for cmd in parse_commands(settings.command or ["help"]):
        print(">>> %s" % json.dumps(cmd), file=sys.stderr)
        ret = conn.command(cmd)
        print(json.dumps(ret, indent=2))


if __name__ == "__main__":
    main(sys.argv)
