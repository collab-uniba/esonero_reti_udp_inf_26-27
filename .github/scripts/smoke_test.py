#!/usr/bin/env python3
"""Smoke test for the unit converter assignment.

Checks the student client and server against a reference implementation of
the application protocol, using the examples in Assegnazione.md. Passing this test
does NOT guarantee a pass in the final grading, which uses further cases.

Usage: smoke_test.py CLIENT_EXE SERVER_EXE
"""

import os
import select
import socket
import struct
import subprocess
import sys
import math
import tempfile
import time

HOST = "127.0.0.1"
DEFAULT_PORT = 56700
REF_PORT = 56701
CLOSED_PORT = 56702
OPTION_PORT = 56703  # server started with -p
TIMEOUT = 5
CLIENT_TIMEOUT = 10  # longer than the client's own receive timeout (TIMEOUT_SEC)
MAX_VALUE = 1000.0
PREFIX = "Ricevuto risultato dal server 127.0.0.1 (ip 127.0.0.1). "        # client run with -s 127.0.0.1
DEFAULT_PREFIX = "Ricevuto risultato dal server localhost (ip 127.0.0.1). "  # client run without -s

UNITS = {  # (quantity, 1 unit in metres or kilograms)
    "m": ("L", 1.0), "km": ("L", 1000.0), "ft": ("L", 0.3048),
    "yd": ("L", 0.9144), "mi": ("L", 1609.344),
    "g": ("M", 0.001), "kg": ("M", 1.0), "oz": ("M", 0.028349523),
    "lb": ("M", 0.45359237),
}

# (-r argument, expected client output after PREFIX, expected server log)
CASES = [
    ("mi km 26.2", "26.20 mi = 42.16 km", "Richiesta 'mi km 26.20' dal client ip 127.0.0.1"),
    ("km mi 10", "10.00 km = 6.21 mi", "Richiesta 'km mi 10.00' dal client ip 127.0.0.1"),
    ("m ft 100", "100.00 m = 328.08 ft", "Richiesta 'm ft 100.00' dal client ip 127.0.0.1"),
    ("ft m 1", "1.00 ft = 0.30 m", "Richiesta 'ft m 1.00' dal client ip 127.0.0.1"),
    ("kg lb 70.5", "70.50 kg = 155.43 lb", "Richiesta 'kg lb 70.50' dal client ip 127.0.0.1"),
    ("lb oz 2.5", "2.50 lb = 40.00 oz", "Richiesta 'lb oz 2.50' dal client ip 127.0.0.1"),
    ("yd yd 12.34", "12.34 yd = 12.34 yd", "Richiesta 'yd yd 12.34' dal client ip 127.0.0.1"),
    ("mi ft 1000", "1000.00 mi = 5280000.00 ft", "Richiesta 'mi ft 1000.00' dal client ip 127.0.0.1"),
    ("KM mi 1", "Simbolo non supportato", "Richiesta 'KM mi 1.00' dal client ip 127.0.0.1"),
    ("m xyz 0", "Simbolo non supportato", "Richiesta 'm xyz 0.00' dal client ip 127.0.0.1"),
    ("km kg 0", "Grandezze incompatibili", "Richiesta 'km kg 0.00' dal client ip 127.0.0.1"),
    ("m km -5", "Valore non valido", "Richiesta 'm km -5.00' dal client ip 127.0.0.1"),
    ("g kg 0", "Valore non valido", "Richiesta 'g kg 0.00' dal client ip 127.0.0.1"),
    ("lb kg 1000.01", "Valore non valido", "Richiesta 'lb kg 1000.01' dal client ip 127.0.0.1"),
]

# Request the server must ignore when it comes in a datagram longer than 12 bytes
LONG_REQUEST = "g kg 7"
LONG_REQUEST_LOG = "'g kg 7.00'"

USAGE = 'Uso: client-project [-s server] [-p port] -r "FROM TO valore"'
EXIT_FAILURE = 1  # value of EXIT_FAILURE on Windows, Linux and macOS

USAGE_CASES = ["mile km 10", "m km abc", "m km 10,50", "m km", "m km 10 20"]

BYTE_ORDER_HINT = "sembra un errore di byte order: hai usato htonl()/ntohl()?"
FLOAT_HINT = "sembra che il float sia stato convertito in intero: vanno copiati i suoi bit con memcpy()"

results = []  # (section, name, ok, detail)


def check(section, name, ok, detail=""):
    results.append((section, name, ok, detail))
    print("[%s] %s: %s%s" % ("OK" if ok else "FAIL", section, name, "" if ok else " -> " + detail))


def to_float32(x):
    """Round a Python float to IEEE 754 single precision, like a C float."""
    return struct.unpack("!f", struct.pack("!f", x))[0]


def same_float(a, b):
    """Equal up to one float32 rounding (compilers may differ in the last bit)."""
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def parse_request(req):
    frm, to, value = req.split(" ")
    return frm, to, to_float32(float(value))


def reference_response(frm, to, value):
    unit_from, unit_to = UNITS.get(frm), UNITS.get(to)
    if unit_from is None or unit_to is None:
        return 1, 0
    if unit_from[0] != unit_to[0]:
        return 2, 0
    if not (value > 0 and value <= MAX_VALUE):
        return 3, 0.0
    factor_from, factor_to = unit_from[1], unit_to[1]
    return 0, to_float32(value * factor_from / factor_to)  # convert(): double math, float result


def normalize(out):
    return out.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")


def executable(path):
    path = os.path.abspath(path)
    if os.name == "nt" and not path.lower().endswith(".exe"):
        path += ".exe"
    return path


def run_client(client, args):
    try:
        proc = subprocess.run([client] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, timeout=CLIENT_TIMEOUT)
        return proc.returncode, normalize(proc.stdout), None
    except subprocess.TimeoutExpired:
        return None, "", "il client non termina entro %d s" % CLIENT_TIMEOUT
    except OSError as e:
        return None, "", "impossibile eseguire il client: %s" % e


def exchange(port, payload):
    """Send one request datagram to the server and return the response datagram."""
    deadline = time.time() + TIMEOUT
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.5)
        while True:
            # Sent again until the deadline: the server may not be bound yet
            sock.sendto(payload, (HOST, port))
            try:
                data, addr = sock.recvfrom(1024)
                break
            except (socket.timeout, ConnectionResetError):  # Windows: nobody on the port (yet)
                if time.time() > deadline:
                    raise OSError("nessuna risposta entro %d s" % TIMEOUT)
                time.sleep(0.2)
    if addr[1] != port:
        raise OSError("la risposta arriva dalla porta %d invece che dalla %d: rispondi con lo "
                      "stesso socket su cui hai ricevuto la richiesta" % (addr[1], port))
    return data


def ignored(port, payload):
    """True if the server sends no response to the datagram within one second."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1)
        sock.sendto(payload, (HOST, port))
        try:
            sock.recvfrom(1024)
            return False
        except (socket.timeout, ConnectionResetError):
            return True


def test_server(server, client):
    section = "server"
    log = tempfile.TemporaryFile()
    errors = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen([server], stdout=log, stderr=errors, stdin=subprocess.DEVNULL)
    except OSError as e:
        check(section, "avvio", False, "impossibile eseguire il server: %s" % e)
        return
    time.sleep(1)
    if proc.poll() is not None:
        errors.seek(0)
        stderr = normalize(errors.read()).strip()
        check(section, "avvio", False, "il server termina subito (exit code %s)%s"
              % (proc.returncode, (": " + stderr.replace("\n", " | ")) if stderr else ""))
        return
    check(section, "avvio", True)

    expected_log = []
    for req, _, log_line in CASES:
        frm, to, value = parse_request(req)
        payload = struct.pack("!4s4sf", frm.encode(), to.encode(), value)
        name = "risposta a '%s'" % req
        try:
            data = exchange(DEFAULT_PORT, payload)
        except OSError as e:
            check(section, name, False, "errore di comunicazione sulla porta %d: %s (richieste "
                  "successive saltate)" % (DEFAULT_PORT, e))
            break
        expected_log.append(log_line)
        if len(data) != 8:
            check(section, name, False, "ricevuti %d byte invece di 8" % len(data))
            continue
        got = struct.unpack("!If", data)
        expected = reference_response(frm, to, value)
        if got[0] == expected[0] and same_float(got[1], expected[1]):
            check(section, name, True)
        else:
            detail = "status/value = (%d, %g), attesi (%d, %g)" % (got[0], got[1], expected[0], expected[1])
            got_le = struct.unpack("<If", data)
            if (got_le[0] == expected[0] and same_float(got_le[1], expected[1])) \
                    or (got[0] > 3 and got_le[0] <= 3):
                detail += "; " + BYTE_ORDER_HINT
            elif got[0] == expected[0] and struct.unpack("!I", data[4:8])[0] == int(expected[1]):
                detail += "; " + FLOAT_HINT
            check(section, name, False, detail)

    # Datagrams of the wrong size must be ignored: no response, no log line
    if expected_log:
        frm, to, value = parse_request(LONG_REQUEST)
        for name, payload in (("datagramma troppo corto (5 byte) ignorato", b"m\0\0\0k"),
                              ("datagramma troppo lungo (20 byte) ignorato",
                               struct.pack("!4s4sf", frm.encode(), to.encode(), value) + bytes(8))):
            if not ignored(DEFAULT_PORT, payload):
                check(section, name, False, "il server ha risposto: i datagrammi di dimensione diversa "
                      "da 12 byte vanno ignorati (per quelli piu' lunghi, ricevi in un buffer piu' "
                      "grande e controlla quanti byte restituisce recvfrom)")
            elif proc.poll() is not None:
                check(section, name, False, "il server e' terminato (exit code %s): un datagramma non "
                      "valido o un errore di recvfrom non devono chiudere il server" % proc.returncode)
                return
            else:
                check(section, name, True)

    # End-to-end: student client against student server, default address and port
    code, out, err = run_client(client, ["-r", CASES[0][0]])
    expected_out = DEFAULT_PREFIX + CASES[0][1]
    if err:
        check("end-to-end", "client e server con parametri di default", False, err)
    else:
        expected_log.append(CASES[0][2])
        check("end-to-end", "client e server con parametri di default", code == 0 and out == expected_out,
              "exit code %s, output %r, atteso %r" % (code, out, expected_out))

    proc.terminate()
    try:
        proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.seek(0)
    lines = normalize(log.read()).split("\n")
    missing = [line for line in expected_log if line not in lines]
    if not expected_log:  # no request reached the server: nothing to verify
        return
    check(section, "nessun log per i datagrammi ignorati", not any(LONG_REQUEST_LOG in l for l in lines),
          "il server ha stampato il log del datagramma troppo lungo %s" % LONG_REQUEST_LOG)
    check(section, "log delle richieste", not missing,
          "righe mancanti o diverse, ad es. %r (righe stampate: %r). Se non stampa nulla, "
          "chiama fflush(stdout) dopo ogni printf" % (missing[0] if missing else "", lines[:3]))


def test_server_port_option(server):
    """The server started with -p PORT listens on that port and answers."""
    section, name = "server", "avvio con -p %d" % OPTION_PORT
    try:
        errors = tempfile.TemporaryFile()
        proc = subprocess.Popen([server, "-p", str(OPTION_PORT)], stdout=subprocess.DEVNULL,
                                stderr=errors, stdin=subprocess.DEVNULL)
    except OSError as e:
        check(section, name, False, "impossibile eseguire il server: %s" % e)
        return
    try:
        time.sleep(1)
        if proc.poll() is not None:
            errors.seek(0)
            stderr = normalize(errors.read()).strip()
            check(section, name, False, "il server termina subito (exit code %s)%s; controlla la "
                  "lettura degli argomenti: il valore dopo -p non e' un argomento a se'"
                  % (proc.returncode, (": " + stderr.replace("\n", " | ")) if stderr else ""))
            return
        req = CASES[0][0]
        frm, to, value = parse_request(req)
        try:
            data = exchange(OPTION_PORT, struct.pack("!4s4sf", frm.encode(), to.encode(), value))
        except OSError as e:
            check(section, name, False, "errore di comunicazione sulla porta %d: %s" % (OPTION_PORT, e))
            return
        ok = len(data) == 8 and struct.unpack("!I", data[:4])[0] == reference_response(frm, to, value)[0]
        check(section, name, ok, "nessuna risposta corretta a '%s' sulla porta %d" % (req, OPTION_PORT))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()


def drain(sock):
    """Discard datagrams left over from a previous test."""
    while select.select([sock], [], [], 0)[0]:
        try:
            sock.recvfrom(1024)
        except ConnectionResetError:  # Windows: ICMP from a response sent to a closed client
            pass


def serve_reference(sock, mode=None):
    """Read one request datagram and reply as the reference server. Returns the raw request.

    mode "other_port": the response comes from another port; "long": one extra byte.
    """
    data, addr = sock.recvfrom(1024)
    if len(data) == 12:
        frm = data[0:4].split(b"\0")[0].decode("ascii", errors="replace")
        to = data[4:8].split(b"\0")[0].decode("ascii", errors="replace")
        value = struct.unpack("!f", data[8:12])[0]
        response = struct.pack("!If", *reference_response(frm, to, value))
        if mode == "other_port":
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
                other.bind((HOST, 0))
                other.sendto(response, addr)
        else:
            sock.sendto(response + (b"\0" if mode == "long" else b""), addr)
    return data


def client_vs_reference(client, args, sock, mode=None):
    """Run the client against the reference server.

    Returns (exit code, stdout, raw request or None if no request was sent, error).
    """
    drain(sock)
    try:
        proc = subprocess.Popen([client] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL)
    except OSError as e:
        return None, "", None, "impossibile eseguire il client: %s" % e
    request, error = None, None
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        exited = proc.poll() is not None
        if select.select([sock], [], [], 0.3 if exited else 0.1)[0]:
            try:
                request = serve_reference(sock, mode)
            except ConnectionResetError:  # Windows: stale ICMP, not the client's request
                continue
            except OSError as e:
                request, error = b"", "errore di comunicazione: %s" % e
            break
        if exited:
            break
    try:
        out, _ = proc.communicate(timeout=CLIENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None, "", request, "il client non termina entro %d s" % CLIENT_TIMEOUT
    return proc.returncode, normalize(out), request, error


def check_request(data, frm, to, value):
    if data is None:
        return "nessuna richiesta ricevuta"
    if len(data) != 12:
        return "ricevuti %d byte invece di 12" % len(data)
    if b"\0" not in data[0:4] or b"\0" not in data[4:8]:
        return "i campi from/to devono terminare con '\\0' entro i 4 byte"
    got_from = data[0:4].split(b"\0")[0].decode("ascii", "replace")
    got_to = data[4:8].split(b"\0")[0].decode("ascii", "replace")
    if (got_from, got_to) != (frm, to):
        return "simboli ricevuti %r, attesi %r" % ((got_from, got_to), (frm, to))
    got = struct.unpack("!f", data[8:12])[0]
    if not same_float(got, value):
        detail = "value ricevuto %g, atteso %g" % (got, value)
        if same_float(struct.unpack("<f", data[8:12])[0], value):
            detail += "; " + BYTE_ORDER_HINT
        elif struct.unpack("!I", data[8:12])[0] == int(value):
            detail += "; " + FLOAT_HINT
        return detail
    return None


def test_client(client):
    section = "client"
    ref = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ref.bind((HOST, REF_PORT))
    port_args = ["-s", HOST, "-p", str(REF_PORT)]

    for req, expected_out, _ in CASES:
        frm, to, value = parse_request(req)
        name = "output per '%s'" % req
        code, out, request, err = client_vs_reference(client, port_args + ["-r", req], ref)
        if err:
            check(section, name, False, err)
            continue
        if request is None:
            check(section, name, False, "il client non invia la richiesta al server (controlla -s e -p)")
            continue
        problem = check_request(request, frm, to, value)
        if problem:
            check(section, name, False, "richiesta errata: " + problem)
            continue
        expected_out = PREFIX + expected_out
        check(section, name, code == 0 and out == expected_out,
              "exit code %s, output %r, atteso %r" % (code, out, expected_out))

    for req in USAGE_CASES:
        name = "argomenti non validi '%s'" % req
        code, out, request, err = client_vs_reference(client, port_args + ["-r", req], ref)
        if err:
            check(section, name, False, err)
        else:
            check(section, name, code == EXIT_FAILURE and out == USAGE and request is None,
                  "attesi la riga %r su stdout, EXIT_FAILURE (%d) e nessuna richiesta inviata "
                  "(exit code %s, output %r, richiesta: %s)"
                  % (USAGE, EXIT_FAILURE, code, out, "no" if request is None else "si"))

    # The client accepts only a response of the right size from the server's address and port
    for mode, name in (("other_port", "risposta da un'altra porta rifiutata"),
                       ("long", "risposta troppo lunga (9 byte) rifiutata")):
        code, out, request, err = client_vs_reference(client, port_args + ["-r", CASES[0][0]], ref, mode)
        if err:
            check(section, name, False, err)
        else:
            check(section, name, request is not None and code == EXIT_FAILURE and not out.startswith(PREFIX),
                  "atteso EXIT_FAILURE (%d) senza risultato (exit code %s, output %r)"
                  % (EXIT_FAILURE, code, out))
    ref.close()

    code, out, err = run_client(client, ["-s", HOST, "-p", str(CLOSED_PORT), "-r", CASES[0][0]])
    check(section, "server non raggiungibile",
          not err and code == EXIT_FAILURE and not out.startswith(PREFIX),
          err or "atteso EXIT_FAILURE (%d) (exit code %s, output %r)" % (EXIT_FAILURE, code, out))


def write_summary():
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("## Smoke test\n\n| Esito | Area | Verifica | Dettaglio |\n|---|---|---|---|\n")
        for section, name, ok, detail in results:
            f.write("| %s | %s | %s | %s |\n" % ("✅" if ok else "❌", section, name.replace("|", "\\|"),
                                               "" if ok else detail.replace("|", "\\|")))
        f.write("\n> Il superamento dello smoke test non garantisce il superamento della correzione finale.\n")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    # On Windows a piped stdout is cp1252: avoid crashing on the student's output
    sys.stdout.reconfigure(errors="replace")
    client, server = executable(sys.argv[1]), executable(sys.argv[2])
    test_client(client)
    test_server(server, client)
    test_server_port_option(server)
    write_summary()
    failed = sum(1 for r in results if not r[2])
    print("\n%d verifiche, %d fallite" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
