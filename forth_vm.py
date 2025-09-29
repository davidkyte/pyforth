#!/usr/bin/env python3
# forth_vm.py — Heap-based Forth VM (no Python dicts for words)
# Full script with: error handling, HEX/DECIMAL, ?DUP/PICK/ROLL/DEPTH/CLEAR,
# SLEEP/MS, IF/ELSE/THEN, BEGIN/AGAIN/UNTIL/WHILE/REPEAT, DO/LOOP/+LOOP/I/J/LEAVE,
# CREATE/DOES>, CONSTANT/VARIABLE (+ legacy *_2), loader, REPL.

import sys, time

class ExitFrame(Exception):
    pass

IMMEDIATE_FLAG = 0x80  # High bit in flags|namelen cell = IMMEDIATE

class ForthVM:
    def __init__(self):
        # Stacks
        self.S = []     # Data stack
        self.R = []     # Return stack

        # Heap-backed dictionary
        self.heap = [0] * (64 * 1024)
        self.here = 1
        self.latest = 0

        # Compiler / defining state
        self.runtime_created_header = None
        self.pending_does = []          # list of (install_pos, branch_pos, body_index)
        self.base = 10
        self.compiling = False
        self.current_code_list = None
        self.current_code_cfaddr = None
        self.ctrl_stack = []            # control-structure patch info

        # Input buffer
        self._input_buffer = []
        self._in_pointer = 0

        # Bootstrap
        self._install_kernel()
        self._install_highlevel()

    # ====== Stack ======
    def push(self, x): self.S.append(x)
    def pop(self):
        if not self.S: raise RuntimeError("Stack underflow")
        return self.S.pop()

    # ====== Dictionary headers ======
    # Header layout: [link][flags|namelen][name chars...][code field]
    def _allocate_word_header(self, name, is_immediate=False):
        header_addr = self.here
        # link
        self.heap[self.here] = self.latest; self.here += 1
        # flags|len
        flags = IMMEDIATE_FLAG if is_immediate else 0
        self.heap[self.here] = flags | len(name); self.here += 1
        # name
        for ch in name:
            self.heap[self.here] = ord(ch); self.here += 1
        # code field (placeholder)
        cf = self.here
        self.heap[self.here] = None; self.here += 1
        # update latest
        self.latest = header_addr
        return cf

    def add_fn(self, name, fn, immediate=False):
        cf = self._allocate_word_header(name, is_immediate=immediate)
        self.heap[cf] = fn

    def _find_word(self, nameU):
        p = self.latest
        while p:
            q = p + 1
            flags_len = self.heap[q]; q += 1
            nlen = flags_len & 0x3F
            wname = "".join(chr(self.heap[q+i]) for i in range(nlen))
            if wname.upper() == nameU:
                return p
            p = self.heap[p]
        return None

    def _word_fields(self, w_addr):
        q = w_addr + 1
        flags_len = self.heap[q]; q += 1
        nlen = flags_len & 0x3F
        cf = q + nlen
        return flags_len, nlen, cf

    # ====== Panic/reset ======
    def _panic(self, e=None):
        if e is not None:
            print("ERR:", e)
        # If compiling, unlink half-built header
        if self.compiling and self.latest:
            prev = self.heap[self.latest]  # link field
            self.latest = prev
        # Reset volatile state
        self.S.clear(); self.R.clear()
        self.compiling = False
        self.current_code_list = None
        self.current_code_cfaddr = None
        self.ctrl_stack.clear()
        self.pending_does = []
        self.runtime_created_header = None
        self._input_buffer = []; self._in_pointer = 0

    # ====== Execution engine ======
    def execute(self, w_addr):
        _, _, cf = self._word_fields(w_addr)
        code = self.heap[cf]
        if callable(code):
            code(self); return
        if isinstance(code, tuple) and code[0] == "THREAD":
            start, count = code[1], code[2]
            ops = self.heap[start:start+count]
            self._exec_thread(ops); return
        raise RuntimeError("Bad code field")

    def _exec_thread(self, ops):
        ip = 0
        while True:
            if ip >= len(ops): return
            op = ops[ip]; ip += 1
            if callable(op):
                op(self); continue
            if not isinstance(op, tuple):
                raise RuntimeError(f"Bad op {op!r}")
            tag = op[0]
            if tag == "LIT":
                self.push(op[1])
            elif tag == "CALL_ADDR":
                self.execute(op[1])
            elif tag == "BRANCH":
                if op[1] is None: raise RuntimeError("Unpatched BRANCH encountered")
                ip = op[1]
            elif tag == "0BRANCH":
                if op[1] is None: raise RuntimeError("Unpatched 0BRANCH encountered")
                flag = self.pop()
                if flag == 0: ip = op[1]
            else:
                raise RuntimeError(f"Bad thread tag {tag}")

    # ====== Tokenizer ======
    def _tokenize(self, line):
        s=line; i=0; n=len(s); out=[]
        while i<n:
            while i<n and s[i].isspace(): i+=1
            if i>=n: break
            if s[i]=='\\': break  # backslash comment to end of line
            if s[i]=='(':
                i+=1
                while i<n and s[i]!=')': i+=1
                if i<n: i+=1
                continue
            if s[i]=='.' and i+1<n and s[i+1]=='"':
                i+=2
                if i<n and s[i]==' ': i+=1
                start=i
                while i<n and s[i]!='"': i+=1
                text=s[start:i]
                if i<n: i+=1
                out.append(('DOTQUOTE', text)); continue
            start=i
            while i<n and not s[i].isspace():
                if s[i] in ['\\','('] or (s[i]=='.' and i+1<n and s[i+1]=='"'):
                    break
                i+=1
            out.append(s[start:i])
        return out

    def parse_token(self):
        if self._in_pointer>=len(self._input_buffer): return None
        t=self._input_buffer[self._in_pointer]; self._in_pointer+=1; return t
    def _next_token(self): return self.parse_token()
    def _parse_number(self, tok):
        try: return int(tok, self.base)
        except: return None

    # ====== Interpreter / compiler ======
    def interpret(self, line):
        self._input_buffer=self._tokenize(line); self._in_pointer=0
        while self._in_pointer < len(self._input_buffer):
            tok=self.parse_token()
            if tok is None: break
            self._interpret_token(tok)

    def _emit_op(self, op): self.current_code_list.append(op)
    def _patch_op(self, idx, op): self.current_code_list[idx]=op

    def _interpret_token(self, tok):
        # ." string "
        if isinstance(tok, tuple) and tok[0]=="DOTQUOTE":
            text=tok[1]
            if self.compiling:
                def _print(vm, s=text): sys.stdout.write(s+" ")
                self._emit_op(_print)
            else:
                sys.stdout.write(text+" ")
            return

        if not isinstance(tok, str):
            raise RuntimeError(f"Bad token {tok!r}")
        tU = tok.upper()

        # Start colon definition
        if tU == ":":
            self.compiling=True
            name=self._next_token()
            if not name: raise RuntimeError("Missing name after ':'")
            name = name.upper()   # force uppercase dictionary names
            cf=self._allocate_word_header(name)
            self.heap[cf]=("THREAD", None, None)
            self.current_code_cfaddr=cf
            self.current_code_list=[]
            self.ctrl_stack=[]
            self.pending_does=[]
            return

        # End colon definition
        if self.compiling and tU == ";":
            # Patch DOES>-skip branches before copying
            for (_, branch_pos, _) in self.pending_does:
                self._patch_op(branch_pos, ("BRANCH", len(self.current_code_list)))
            # Copy ops into heap
            start=self.here
            for op in self.current_code_list:
                self.heap[self.here]=op; self.here+=1
            count=len(self.current_code_list)
            # Set code field to thread
            self.heap[self.current_code_cfaddr]=("THREAD", start, count)
            # Replace install stubs with runtime patchers (for DOES>)
            for (install_pos, _branch_pos, body_index) in self.pending_does:
                seg_start = start + body_index
                seg_count = count - body_index
                def _install_does(vm, ss=seg_start, cc=seg_count):
                    hdr = vm.runtime_created_header
                    if hdr is None:
                        raise RuntimeError("DOES>: no CREATE executed at run time")
                    cfaddr = vm._word_fields(hdr)[2]
                    pfa = cfaddr + 1
                    def _does_runtime(vmm, addr=pfa, s=ss, c=cc):
                        vmm.push(addr)
                        ops = vmm.heap[s:s+c]
                        vmm._exec_thread(ops)
                    vm.heap[cfaddr] = _does_runtime
                self.heap[start + install_pos] = _install_does
            # Reset compiler state
            self.compiling=False
            self.current_code_list=None
            self.current_code_cfaddr=None
            self.pending_does=[]
            return

        # Compile state (not ';')
        if self.compiling:
            n=self._parse_number(tok)
            if n is not None:
                self._emit_op(("LIT", n)); return
            w=self._find_word(tU)
            if w is None: raise RuntimeError(f"Unknown during compile: {tok}")
            flags_len,_,_=self._word_fields(w)
            if flags_len & IMMEDIATE_FLAG:
                self.execute(w)  # run now
            else:
                self._emit_op(("CALL_ADDR", w))
            return

        # Interpret state
        n=self._parse_number(tok)
        if n is not None: self.push(n); return
        w=self._find_word(tU)
        if w is None: raise RuntimeError(f"Unknown word: {tok}")
        self.execute(w)

    # ====== REPL ======
    def repl(self):
        while True:
            try:
                line=input("ok> ")
                if not line: continue
                if line.strip().upper()=="BYE": raise SystemExit
                self.interpret(line)
            except ExitFrame:
                pass
            except (SystemExit, KeyboardInterrupt):
                break
            except Exception as e:
                self._panic(e)

    # ====== Kernel words ======
    def _install_kernel(self):
        # I/O & debug
        self.add_fn(".", lambda vm: sys.stdout.write(str(vm.pop())+" "))
        self.add_fn("CR", lambda vm: sys.stdout.write("\n"))
        self.add_fn("EMIT", lambda vm: sys.stdout.write(chr(vm.pop() & 0xFF)))

        def WORDS(vm):
            p=vm.latest; names=[]
            while p:
                q=p+1; fl=vm.heap[q]; q+=1; nlen=fl&0x3F
                names.append("".join(chr(vm.heap[q+i]) for i in range(nlen)))
                p=vm.heap[p]
            sys.stdout.write(" ".join(names)+"\n")
        self.add_fn("WORDS", WORDS)

        def DOT_S(vm):
            sys.stdout.write(f"<{len(vm.S)}> ")
            for x in vm.S: sys.stdout.write(str(x)+" ")
            sys.stdout.write("\n")
        self.add_fn(".S", DOT_S)

        # Stack ops
        self.add_fn("DROP", lambda vm: vm.pop())
        self.add_fn("DUP",  lambda vm: vm.push(vm.S[-1]))
        self.add_fn("?DUP", lambda vm: (vm.S.append(vm.S[-1]) if vm.S and vm.S[-1]!=0 else None))
        def SWAP(vm): vm.S[-1], vm.S[-2] = vm.S[-2], vm.S[-1]
        self.add_fn("SWAP", SWAP)
        self.add_fn("OVER", lambda vm: vm.push(vm.S[-2]))
        self.add_fn("DEPTH", lambda vm: vm.push(len(vm.S)))
        self.add_fn("CLEAR", lambda vm: vm.S.clear())

        def PICK(vm):
            u=vm.pop()
            if u<0 or u>=len(vm.S): raise RuntimeError("PICK range")
            vm.push(vm.S[-u-1])
        self.add_fn("PICK", PICK)

        def ROLL(vm):
            u=vm.pop()
            if u<0 or u>=len(vm.S): raise RuntimeError("ROLL range")
            val=vm.S[-u-1]; del vm.S[-u-1]; vm.push(val)
        self.add_fn("ROLL", ROLL)

        # Arithmetic
        self.add_fn("+", lambda vm: vm.push(vm.pop() + vm.pop()))
        def MINUS(vm): a=vm.pop(); b=vm.pop(); vm.push(b - a)
        def TIMES(vm): a=vm.pop(); b=vm.pop(); vm.push(b * a)
        def DIV(vm):   a=vm.pop(); b=vm.pop(); vm.push(b // a)
        self.add_fn("-", MINUS)
        self.add_fn("*", TIMES)
        self.add_fn("/", DIV)

        # Comparators -> Forth booleans
        self.add_fn("=", lambda vm: vm.push(-1 if vm.pop()==vm.pop() else 0))
        self.add_fn("<", lambda vm: (lambda a,b: vm.push(-1 if b<a else 0))(vm.pop(), vm.pop()))
        self.add_fn(">", lambda vm: (lambda a,b: vm.push(-1 if b>a else 0))(vm.pop(), vm.pop()))

        # Sleep
        self.add_fn("SLEEP", lambda vm: time.sleep(vm.pop()))
        self.add_fn("MS",    lambda vm: time.sleep(vm.pop()/1000.0))

        # Return stack
        self.add_fn(">R", lambda vm: vm.R.append(vm.pop()))
        self.add_fn("R>", lambda vm: vm.push(vm.R.pop()))
        self.add_fn("R@", lambda vm: vm.push(vm.R[-1]))

        # Memory
        self.add_fn("HERE", lambda vm: vm.push(self.here))
        def COMMA(vm): v=vm.pop(); vm.heap[vm.here]=v; vm.here+=1
        self.add_fn(",", COMMA)
        def STORE(vm): addr=vm.pop(); val=vm.pop(); vm.heap[addr]=val
        def FETCH(vm): addr=vm.pop(); vm.push(vm.heap[addr])
        self.add_fn("!", STORE)
        self.add_fn("@", FETCH)

        # Base switching
        self.add_fn("DECIMAL", lambda vm: setattr(vm, "base", 10))
        self.add_fn("HEX",     lambda vm: setattr(vm, "base", 16))

        # EXIT / BYE
        self.add_fn("EXIT", lambda vm: (_ for _ in ()).throw(ExitFrame()), immediate=True)
        self.add_fn("BYE",  lambda vm: (_ for _ in ()).throw(SystemExit()))

        # ----- Control flow (immediate) -----
        def need_compile(name):
            if not self.compiling: raise RuntimeError(f"{name} only valid during compilation")

        # IF/ELSE/THEN
        def W_IF(vm):
            need_compile("IF")
            vm.current_code_list.append(("0BRANCH", None))
            vm.ctrl_stack.append(("IF", len(vm.current_code_list)-1))
        self.add_fn("IF", W_IF, immediate=True)

        def W_ELSE(vm):
            need_compile("ELSE")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "IF":
                raise RuntimeError("ELSE without IF")
            _, ifpos = vm.ctrl_stack.pop()
            vm.current_code_list.append(("BRANCH", None))
            branch_pos = len(vm.current_code_list)-1
            vm._patch_op(ifpos, ("0BRANCH", len(vm.current_code_list)))
            vm.ctrl_stack.append(("ELSE", branch_pos))
        self.add_fn("ELSE", W_ELSE, immediate=True)

        def W_THEN(vm):
            need_compile("THEN")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] not in ("IF","ELSE"):
                raise RuntimeError("THEN without IF/ELSE")
            _, pos = vm.ctrl_stack.pop()
            tag = vm.current_code_list[pos][0]
            vm._patch_op(pos, (tag, len(vm.current_code_list)))
        self.add_fn("THEN", W_THEN, immediate=True)

        # BEGIN/AGAIN/UNTIL/WHILE/REPEAT
        def W_BEGIN(vm):
            need_compile("BEGIN")
            vm.ctrl_stack.append(("BEGIN", len(vm.current_code_list)))
        self.add_fn("BEGIN", W_BEGIN, immediate=True)

        def W_AGAIN(vm):
            need_compile("AGAIN")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "BEGIN":
                raise RuntimeError("AGAIN without BEGIN")
            _, bpos = vm.ctrl_stack.pop()
            vm.current_code_list.append(("BRANCH", bpos))
        self.add_fn("AGAIN", W_AGAIN, immediate=True)

        def W_UNTIL(vm):
            need_compile("UNTIL")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "BEGIN":
                raise RuntimeError("UNTIL without BEGIN")
            _, bpos = vm.ctrl_stack.pop()
            vm.current_code_list.append(("0BRANCH", bpos))
        self.add_fn("UNTIL", W_UNTIL, immediate=True)

        def W_WHILE(vm):
            need_compile("WHILE")
            # find nearest BEGIN
            bpos=None
            for i in range(len(vm.ctrl_stack)-1, -1, -1):
                if vm.ctrl_stack[i][0] == "BEGIN":
                    bpos = vm.ctrl_stack[i][1]; break
            if bpos is None: raise RuntimeError("WHILE without BEGIN")
            vm.current_code_list.append(("0BRANCH", None))
            vm.ctrl_stack.append(("WHILE", len(vm.current_code_list)-1, bpos))
        self.add_fn("WHILE", W_WHILE, immediate=True)

        def W_REPEAT(vm):
            need_compile("REPEAT")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "WHILE":
                raise RuntimeError("REPEAT without WHILE")
            _, while_pos, bpos = vm.ctrl_stack.pop()
            vm.current_code_list.append(("BRANCH", bpos))
            vm._patch_op(while_pos, ("0BRANCH", len(vm.current_code_list)))
            # remove matching BEGIN marker
            for i in range(len(vm.ctrl_stack)-1, -1, -1):
                if vm.ctrl_stack[i][0] == "BEGIN" and vm.ctrl_stack[i][1] == bpos:
                    vm.ctrl_stack.pop(i); break
        self.add_fn("REPEAT", W_REPEAT, immediate=True)

        # ----- Defining words -----
        def W_CREATE(vm):
            name = vm._next_token()
            if not name: raise RuntimeError("CREATE needs a name")
            cf = vm._allocate_word_header(name)
            header = vm.latest
            pfa = cf + 1
            # Default runtime for the created word: push PFA when *that* word runs
            def created_runtime(vmm, addr=pfa): vmm.push(addr)
            vm.heap[cf] = created_runtime
            vm.runtime_created_header = header   # recorded at run time for DOES>
        self.add_fn("CREATE", W_CREATE)

        def W_DOES(vm):
            need_compile("DOES>")
            # Insert an install stub (callable placeholder) *and* a skip-branch.
            install_pos = len(vm.current_code_list)
            vm.current_code_list.append(lambda _vm: None)  # placeholder
            vm.current_code_list.append(("BRANCH", None))  # to be patched to end
            branch_pos = len(vm.current_code_list) - 1
            body_index = len(vm.current_code_list)
            vm.pending_does.append((install_pos, branch_pos, body_index))
        self.add_fn("DOES>", W_DOES, immediate=True)

        # EXIT / BYE (also defined above)
        self.add_fn("EXIT", lambda vm: (_ for _ in ()).throw(ExitFrame()), immediate=True)
        self.add_fn("BYE",  lambda vm: (_ for _ in ()).throw(SystemExit()))

        # ===== Counted loops: DO / LOOP / +LOOP / I / J / LEAVE =====

        # Helpers used in loop threads
        def _loop_enter(vm):
            # ( limit start -- ) => R: ... limit index
            start = vm.pop()
            limit = vm.pop()
            vm.R.append(limit)
            vm.R.append(start)

        def _loop_step_const(vm, step=1):
            # increment index; push f: 0 = continue, -1 = done
            idx = vm.R[-1]; limit = vm.R[-2]
            idx += step
            if idx < limit:
                vm.R[-1] = idx
                vm.push(0)
            else:
                vm.R.pop(); vm.R.pop()
                vm.push(-1)

        def _loop_step_var(vm):
            # ( n -- ) add n to index; push f as above
            step = vm.pop()
            idx = vm.R[-1]; limit = vm.R[-2]
            idx += step
            if idx < limit:
                vm.R[-1] = idx
                vm.push(0)
            else:
                vm.R.pop(); vm.R.pop()
                vm.push(-1)

        def _leave_pop(vm):
            if len(vm.R) < 2: raise RuntimeError("LEAVE without DO")
            vm.R.pop(); vm.R.pop()

        # DO
        def W_DO(vm):
            need_compile("DO")
            vm.current_code_list.append(_loop_enter)
            loop_start = len(vm.current_code_list)
            vm.ctrl_stack.append(("DO", loop_start))
            vm.ctrl_stack.append(("LEAVE-LIST", []))
        self.add_fn("DO", W_DO, immediate=True)

        # LOOP — consumes all flags; no stack junk
        def W_LOOP(vm):
            need_compile("LOOP")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "LEAVE-LIST":
                raise RuntimeError("LOOP: internal leave list missing")
            _, leave_list = vm.ctrl_stack.pop()
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "DO":
                raise RuntimeError("LOOP without DO")
            _, loop_start = vm.ctrl_stack.pop()

            vm.current_code_list.append(_loop_step_const)
            dup_w  = self._find_word("DUP")
            not_w  = self._find_word("NOT")
            drop_w = self._find_word("DROP")
            vm.current_code_list.append(("CALL_ADDR", dup_w))
            vm.current_code_list.append(("CALL_ADDR", not_w))
            if_pos_idx = len(vm.current_code_list)
            vm.current_code_list.append(("0BRANCH", None))
            vm.current_code_list.append(("CALL_ADDR", drop_w))
            vm.current_code_list.append(("BRANCH", loop_start))
            vm.current_code_list[if_pos_idx] = ("0BRANCH", len(vm.current_code_list))
            vm.current_code_list.append(("CALL_ADDR", drop_w))

            for pos in leave_list:
                vm.current_code_list[pos] = ("BRANCH", len(vm.current_code_list))
        self.add_fn("LOOP", W_LOOP, immediate=True)

        # +LOOP
        def W_PLOOP(vm):
            need_compile("+LOOP")
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "LEAVE-LIST":
                raise RuntimeError("+LOOP: internal leave list missing")
            _, leave_list = vm.ctrl_stack.pop()
            if not vm.ctrl_stack or vm.ctrl_stack[-1][0] != "DO":
                raise RuntimeError("+LOOP without DO")
            _, loop_start = vm.ctrl_stack.pop()

            vm.current_code_list.append(_loop_step_var)
            dup_w  = self._find_word("DUP")
            not_w  = self._find_word("NOT")
            drop_w = self._find_word("DROP")
            vm.current_code_list.append(("CALL_ADDR", dup_w))
            vm.current_code_list.append(("CALL_ADDR", not_w))
            if_pos_idx = len(vm.current_code_list)
            vm.current_code_list.append(("0BRANCH", None))
            vm.current_code_list.append(("CALL_ADDR", drop_w))
            vm.current_code_list.append(("BRANCH", loop_start))
            vm.current_code_list[if_pos_idx] = ("0BRANCH", len(vm.current_code_list))
            vm.current_code_list.append(("CALL_ADDR", drop_w))

            for pos in leave_list:
                vm.current_code_list[pos] = ("BRANCH", len(vm.current_code_list))
        self.add_fn("+LOOP", W_PLOOP, immediate=True)

        # I, J
        self.add_fn("I", lambda vm: vm.push(vm.R[-1]))
        self.add_fn("J", lambda vm: vm.push(vm.R[-3]))

        # LEAVE
        def W_LEAVE(vm):
            need_compile("LEAVE")
            vm.current_code_list.append(_leave_pop)
            vm.current_code_list.append(("BRANCH", None))
            br_pos = len(vm.current_code_list)-1
            # record in nearest LEAVE-LIST
            for i in range(len(vm.ctrl_stack)-1, -1, -1):
                if vm.ctrl_stack[i][0] == "LEAVE-LIST":
                    vm.ctrl_stack[i][1].append(br_pos)
                    break
            else:
                raise RuntimeError("LEAVE outside DO...LOOP")
        self.add_fn("LEAVE", W_LEAVE, immediate=True)

    # ====== High-level helpers and definers ======
    def _install_highlevel(self):
        # Loader with error reporting and safe recovery
        def LOAD(vm):
            blk = vm.pop()
            fname = f"{blk}.txt"
            try:
                with open(fname, "r") as f:
                    for lineno, line in enumerate(f, 1):
                        try:
                            vm.interpret(line)
                        except ExitFrame:
                            # normal EXIT from colon def inside file
                            return
                        except Exception as e:
                            print(f"ERR in {fname}:{lineno}:", e)
                            vm._panic()  # unlink half-built word, reset stacks
                            break
            except OSError:
                raise RuntimeError(f"Missing {fname}")
        self.add_fn("LOAD", LOAD)

        # Comfort words
        self.interpret(': 1+ 1 + ;')
        self.interpret(': 1- 1 - ;')
        self.interpret(': 2* DUP + ;')
        self.interpret(': 2/ 2 / ;')
        self.interpret(': NEGATE 0 SWAP - ;')
        self.interpret(': 2DUP OVER OVER ;')
        self.interpret(': 2DROP DROP DROP ;')
        self.interpret(': ROT >R SWAP R> SWAP ;')
        self.interpret(': -ROT SWAP >R SWAP R> ;')
        self.interpret(': NIP SWAP DROP ;')
        self.interpret(': TUCK SWAP OVER ;')
        self.interpret(': SPACE 32 EMIT ;')
        self.interpret(': .CR . CR ;')
        self.interpret(': ? @ . ;')
        self.interpret(': TRUE -1 ;')
        self.interpret(': FALSE 0 ;')
        self.interpret(': NOT 0 = ;')
        self.interpret(': ABS DUP 0 < IF NEGATE THEN ;')
        self.interpret(': MIN 2DUP > IF SWAP THEN DROP ;')
        self.interpret(': MAX 2DUP < IF SWAP THEN DROP ;')

        # Definers via CREATE/DOES>
        self.interpret(': CONSTANT ( n "name" -- ) CREATE , DOES> @ ;')
        self.interpret(': VARIABLE ( "name" -- )    CREATE 0 , DOES> ;')

        # Legacy Python definers
        def W_CONSTANT2(vm):
            name=vm._next_token()
            if not name: raise RuntimeError("CONSTANT2 needs name")
            val=vm.pop()
            vm.add_fn(name, lambda vmm, n=val: vmm.push(n))
        self.add_fn("CONSTANT2", W_CONSTANT2)

        def W_VARIABLE2(vm):
            name=vm._next_token()
            if not name: raise RuntimeError("VARIABLE2 needs name")
            addr=vm.here
            vm.heap[addr]=0; vm.here+=1
            vm.add_fn(name, lambda vmm, a=addr: vmm.push(a))
        self.add_fn("VARIABLE2", W_VARIABLE2)

# Run interactive if called directly
if __name__ == "__main__":
    ForthVM().repl()

