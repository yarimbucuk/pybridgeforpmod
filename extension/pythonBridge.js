// Python Bridge for PenguinMod — unsandboxed
// Connects to pybridgeforpmod on ws://127.0.0.1:8765
(function (Scratch) {
  'use strict';

  if (!Scratch.extensions.unsandboxed) {
    throw new Error('Python Bridge must run unsandboxed.');
  }

  const PORT = 8765;
  const SITE = 'https://pythonbridgeforpenguinmod.vercel.app';
  const INFO = 'python-bridge-pm-v1';

  function scratchBlocks() {
    return window.ScratchBlocks || window.Blockly;
  }

  function b64(bytes) {
    let text = '';
    const raw = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
    for (let i = 0; i < raw.length; i++) text += String.fromCharCode(raw[i]);
    return btoa(text);
  }

  function unb64(text) {
    const raw = atob(text);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function concat(a, b) {
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
  }

  class ClientCrypto {
    async start() {
      this.pair = await crypto.subtle.generateKey(
        { name: 'ECDH', namedCurve: 'P-256' },
        true,
        ['deriveBits']
      );
      this.personal = crypto.getRandomValues(new Uint8Array(32));
      const spki = await crypto.subtle.exportKey('spki', this.pair.publicKey);
      this.publicB64 = b64(spki);
      this.personalB64 = b64(this.personal);
      this.sendN = 0;
      this.recvN = 0;
      this.key = null;
    }

    async finish(serverPublicB64, serverPersonalB64) {
      const peer = await crypto.subtle.importKey(
        'spki',
        unb64(serverPublicB64),
        { name: 'ECDH', namedCurve: 'P-256' },
        true,
        []
      );
      const shared = await crypto.subtle.deriveBits(
        { name: 'ECDH', public: peer },
        this.pair.privateKey,
        256
      );
      const base = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
      const salt = concat(this.personal, unb64(serverPersonalB64));
      this.key = await crypto.subtle.deriveKey(
        { name: 'HKDF', hash: 'SHA-256', salt: salt, info: new TextEncoder().encode(INFO) },
        base,
        { name: 'AES-GCM', length: 256 },
        false,
        ['encrypt', 'decrypt']
      );
    }

    async pack(obj) {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const aad = new TextEncoder().encode(String(this.sendN));
      const n = String(this.sendN);
      this.sendN += 1;
      const ct = await crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv, additionalData: aad },
        this.key,
        new TextEncoder().encode(JSON.stringify(obj))
      );
      return { t: 'enc', n: n, iv: b64(iv), ct: b64(ct) };
    }

    async unpack(packet) {
      const n = parseInt(packet.n, 10);
      if (n !== this.recvN) throw new Error('rejected replayed message');
      this.recvN += 1;
      const raw = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: unb64(packet.iv), additionalData: new TextEncoder().encode(String(n)) },
        this.key,
        unb64(packet.ct)
      );
      return JSON.parse(new TextDecoder().decode(raw));
    }
  }

  function names(block, prefix) {
    const found = [];
    for (let i = 0; i < block.inputList.length; i++) {
      const name = block.inputList[i].name;
      if (name && name.indexOf(prefix) === 0 && name !== prefix + 'BTNS') found.push(name);
    }
    found.sort(function (a, b) {
      return parseInt(a.slice(prefix.length), 10) - parseInt(b.slice(prefix.length), 10);
    });
    return found;
  }

  function fillShadow(block, input) {
    const SB = scratchBlocks();
    const utils = SB && SB.scratchBlocksUtils;
    if (!utils || !input || !input.connection) return;
    try {
      utils.generateMutatorShadow.call(block, input.connection, 'text', '', 'TEXT');
    } catch (e) {}
  }

  function disposeShadow(input) {
    if (!input || !input.connection) return;
    const inner = input.connection.targetBlock();
    if (inner && inner.isShadow && inner.isShadow()) inner.dispose();
  }

  function makeButtons(block, which) {
    const inputName = which === 'param' ? 'PARAMBTNS' : 'DATABTNS';
    if (block.getInput(inputName)) return;
    const SB = scratchBlocks();
    const row = block.appendDummyInput(inputName);
    row.appendField(which === 'param' ? 'parameters' : 'data');
    if (!SB || !SB.FieldExpandableAdd || !SB.FieldExpandableRemove) {
      row.appendField('(+/- missing)');
      return;
    }
    const rem = new SB.FieldExpandableRemove();
    const add = new SB.FieldExpandableAdd();
    rem.showEditor_ = function () { changeGroup(block, which, false); };
    add.showEditor_ = function () { changeGroup(block, which, true); };
    row.appendField(rem);
    row.appendField(add);
  }

  function orderTail(block) {
    const seq = ['PARAMBTNS'].concat(names(block, 'PARAM'), ['DATABTNS'], names(block, 'DATA'));
    for (let i = 0; i < seq.length; i++) {
      if (block.getInput(seq[i]) && block.moveInputBefore) block.moveInputBefore(seq[i], null);
    }
  }

  function changeGroup(block, which, isAdding) {
    const SB = scratchBlocks();
    if (!SB) return;
    const key = which === 'param' ? '_paramCount' : '_dataCount';
    const prefix = which === 'param' ? 'PARAM' : 'DATA';
    const current = Math.max(0, Number(block[key]) || 0);
    if (!isAdding && current === 0) return;
    SB.Events.setGroup(true);
    SB.Events.expandableClick = true;
    const oldMutation = SB.Xml.domToText(block.mutationToDom());
    if (isAdding) {
      const next = current + 1;
      block[key] = next;
      const input = block.appendValueInput(prefix + next);
      fillShadow(block, input);
    } else {
      const input = block.getInput(prefix + current);
      disposeShadow(input);
      if (input) block.removeInput(prefix + current);
      block[key] = current - 1;
    }
    makeButtons(block, 'param');
    makeButtons(block, 'data');
    orderTail(block);
    if (typeof block.initSvg === 'function') block.initSvg();
    if (block.rendered && typeof block.render === 'function') block.render();
    const newMutation = SB.Xml.domToText(block.mutationToDom());
    SB.Events.fire(new SB.Events.BlockChange(block, 'mutation', null, oldMutation, newMutation));
    SB.Events.setGroup(false);
    SB.Events.expandableClick = false;
  }

  function serializeBlock(block, settings) {
    settings.paramcount = String(Math.max(0, Number(block._paramCount) || 0));
    settings.datacount = String(Math.max(0, Number(block._dataCount) || 0));
  }

  function deserializeBlock(block, settings) {
    const paramCount = Math.max(0, parseInt(settings && settings.paramcount, 10) || 0);
    const dataCount = Math.max(0, parseInt(settings && settings.datacount, 10) || 0);
    let paramNames = names(block, 'PARAM');
    while (paramNames.length > paramCount) {
      const last = paramNames[paramNames.length - 1];
      disposeShadow(block.getInput(last));
      if (block.getInput(last)) block.removeInput(last);
      paramNames = names(block, 'PARAM');
    }
    let dataNames = names(block, 'DATA');
    while (dataNames.length > dataCount) {
      const last = dataNames[dataNames.length - 1];
      disposeShadow(block.getInput(last));
      if (block.getInput(last)) block.removeInput(last);
      dataNames = names(block, 'DATA');
    }
    block._paramCount = paramCount;
    block._dataCount = dataCount;
    for (let i = 1; i <= paramCount; i++) {
      if (!block.getInput('PARAM' + i)) fillShadow(block, block.appendValueInput('PARAM' + i));
    }
    for (let i = 1; i <= dataCount; i++) {
      if (!block.getInput('DATA' + i)) fillShadow(block, block.appendValueInput('DATA' + i));
    }
    makeButtons(block, 'param');
    makeButtons(block, 'data');
    orderTail(block);
  }

  function initBlock(block) {
    block.expandable_ = true;
    if (block._paramCount == null) block._paramCount = 0;
    if (block._dataCount == null) block._dataCount = 0;
    makeButtons(block, 'param');
    makeButtons(block, 'data');
    orderTail(block);
  }

  function readShadow(target, input) {
    if (!input || !input.block) return '';
    const child = target.blocks.getBlock(input.block);
    if (!child) return '';
    const fields = child.fields || {};
    if (fields.TEXT) return String(fields.TEXT.value);
    if (fields.NUM) return String(fields.NUM.value);
    return '';
  }

  function collect(args, util, prefix) {
    const values = Object.create(null);
    Object.keys(args || {}).forEach(function (key) {
      if (key.indexOf(prefix) === 0 && key.length > prefix.length) values[key] = args[key];
    });
    try {
      const id = util.thread.peekStack();
      const block = util.target.blocks.getBlock(id);
      const inputs = (block && block.inputs) || {};
      Object.keys(inputs).forEach(function (key) {
        if (key.indexOf(prefix) !== 0 || key.length <= prefix.length) return;
        if (values[key] != null && values[key] !== '') return;
        values[key] = readShadow(util.target, inputs[key]);
      });
    } catch (e) {}
    return Object.keys(values).sort(function (a, b) {
      return parseInt(a.slice(prefix.length), 10) - parseInt(b.slice(prefix.length), 10);
    }).map(function (key) { return values[key]; });
  }

  function asBool(value) {
    if (typeof value === 'boolean') return value;
    const text = String(value).toLowerCase();
    return text === 'true' || text === '1';
  }

  class PythonBridge {
    constructor() {
      this.projectName = 'main';
      this.required = false;
      this.ws = null;
      this.crypto = null;
      this.ready = false;
      this.lastResult = '';
      this.pending = new Map();
      this.overlay = null;
      this._onStart = this._onStart.bind(this);
      if (Scratch.vm) Scratch.vm.runtime.on('PROJECT_START', this._onStart);
    }

    getInfo() {
      const expandable = {
        serialize: serializeBlock,
        deserialize: deserializeBlock,
        init: initBlock
      };
      return {
        id: 'pythonBridgePM',
        name: 'Python Bridge',
        color1: '#306998',
        color2: '#25587F',
        color3: '#1D4666',
        blocks: [
          {
            opcode: 'connect',
            blockType: Scratch.BlockType.COMMAND,
            text: 'connect to python bridge'
          },
          {
            opcode: 'disconnect',
            blockType: Scratch.BlockType.COMMAND,
            text: 'disconnect from python bridge'
          },
          {
            opcode: 'setRequired',
            blockType: Scratch.BlockType.COMMAND,
            text: 'python bridge required for project [REQUIRED]',
            arguments: {
              REQUIRED: {
                type: Scratch.ArgumentType.STRING,
                menu: 'boolMenu',
                defaultValue: 'true'
              }
            }
          },
          {
            opcode: 'connected',
            blockType: Scratch.BlockType.BOOLEAN,
            text: 'python bridge connected?'
          },
          {
            opcode: 'setName',
            blockType: Scratch.BlockType.COMMAND,
            text: 'set name to [NAME]',
            arguments: {
              NAME: { type: Scratch.ArgumentType.STRING, defaultValue: 'main' }
            }
          },
          {
            opcode: 'runCommand',
            blockType: Scratch.BlockType.COMMAND,
            text: 'run [COMMAND]',
            arguments: {
              COMMAND: { type: Scratch.ArgumentType.STRING, defaultValue: 'ping' }
            },
            mutations: expandable
          },
          {
            opcode: 'resultOf',
            blockType: Scratch.BlockType.REPORTER,
            text: 'result of [COMMAND]',
            arguments: {
              COMMAND: { type: Scratch.ArgumentType.STRING, defaultValue: 'ping' }
            },
            mutations: expandable
          },
          {
            opcode: 'addCommand',
            blockType: Scratch.BlockType.COMMAND,
            text: 'add command [COMMAND] with name [NAME]',
            arguments: {
              COMMAND: { type: Scratch.ArgumentType.STRING, defaultValue: 'ping' },
              NAME: { type: Scratch.ArgumentType.STRING, defaultValue: 'main' }
            }
          },
          {
            opcode: 'lastResult',
            blockType: Scratch.BlockType.REPORTER,
            func: 'getLastResult',
            text: 'last python result'
          }
        ],
        menus: {
          boolMenu: {
            acceptReporters: true,
            items: ['true', 'false']
          }
        }
      };
    }

    _onStart() {
      if (this.required && !this.ready) this.showRequired();
    }

    connect() {
      const self = this;
      return this._connect().catch(function (error) {
        self.lastResult = String(error && error.message || error);
        if (self.required) self.showRequired();
      });
    }

    async _connect() {
      if (this.ws) {
        try { this.ws.close(); } catch (e) {}
      }
      this.ready = false;
      const ws = new WebSocket('ws://127.0.0.1:' + PORT);
      this.ws = ws;
      ws.onmessage = (event) => this._onMessage(event);
      ws.onclose = () => {
        this.ready = false;
        if (this.required) this.showRequired();
      };
      await new Promise(function (resolve, reject) {
        let settled = false;
        ws.addEventListener('error', function () {
          if (settled) return;
          settled = true;
          reject(new Error('Python Bridge is not running.'));
        });
        ws.addEventListener('open', function () {
          if (settled) return;
          settled = true;
          resolve();
        });
        ws.addEventListener('close', function () {
          if (settled) return;
          settled = true;
          reject(new Error('Python Bridge is not running.'));
        });
      });
      const crypto = new ClientCrypto();
      await crypto.start();
      this.crypto = crypto;
      const welcomePromise = this._wait('welcome');
      ws.send(JSON.stringify({
        t: 'hello',
        commonPublic: crypto.publicB64,
        personal: crypto.personalB64
      }));
      const welcome = await welcomePromise;
      if (welcome.t === 'paused') throw new Error('Python Bridge is paused.');
      await crypto.finish(welcome.commonPublic, welcome.personal);
      const bound = await this.request({ t: 'bind', name: this.projectName, id: Math.random().toString(16).slice(2) });
      if (!bound || bound.t !== 'bound') throw new Error('Handshake failed.');
      this.ready = true;
      this.hideOverlay();
    }

    _wait(type) {
      const self = this;
      return new Promise(function (resolve, reject) {
        const timer = setTimeout(function () {
          self.pending.delete(type);
          reject(new Error('Python Bridge did not answer.'));
        }, 8000);
        self.pending.set(type, function (message) {
          clearTimeout(timer);
          resolve(message);
        });
      });
    }

    async _onMessage(event) {
      let message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.t === 'welcome' || message.t === 'paused') {
        const waiter = this.pending.get('welcome');
        if (waiter) {
          this.pending.delete('welcome');
          waiter(message);
        }
        return;
      }
      if (message.t !== 'enc' || !this.crypto) return;
      const obj = await this.crypto.unpack(message);
      const waiter = this.pending.get(obj.id) || this.pending.get(obj.t);
      if (waiter) {
        this.pending.delete(obj.id);
        this.pending.delete(obj.t);
        waiter(obj);
      }
    }

    request(obj) {
      const self = this;
      const id = obj.id || Math.random().toString(16).slice(2);
      obj.id = id;
      return new Promise(function (resolve, reject) {
        const timer = setTimeout(function () {
          self.pending.delete(id);
          reject(new Error('Python Bridge timed out.'));
        }, 15000);
        self.pending.set(id, function (message) {
          clearTimeout(timer);
          resolve(message);
        });
        self.crypto.pack(obj).then(function (packet) {
          self.ws.send(JSON.stringify(packet));
        }).catch(function (error) {
          clearTimeout(timer);
          self.pending.delete(id);
          reject(error);
        });
      });
    }

    disconnect() {
      this.ready = false;
      if (this.ws) {
        try { this.ws.close(); } catch (e) {}
        this.ws = null;
      }
      this.crypto = null;
      if (this.required) this.showRequired();
    }

    setRequired(args) {
      this.required = asBool(args.REQUIRED);
      if (this.required && !this.ready) this.showRequired();
      else if (!this.required) this.hideOverlay();
    }

    connected() {
      return this.ready;
    }

    setName(args) {
      this.projectName = Scratch.Cast.toString(args.NAME) || 'main';
      if (!this.ready) return;
      this.request({ t: 'rename', name: this.projectName }).catch(function () {});
    }

    runCommand(args, util) {
      return this._run(args, util, false);
    }

    resultOf(args, util) {
      return this._run(args, util, true);
    }

    _run(args, util, wantValue) {
      const self = this;
      const command = Scratch.Cast.toString(args.COMMAND);
      const parameters = collect(args, util, 'PARAM');
      const data = collect(args, util, 'DATA');
      if (!this.ready) {
        if (this.required) this.showRequired();
        this.lastResult = 'Python Bridge is not connected.';
        return wantValue ? this.lastResult : undefined;
      }
      return this.request({
        t: 'run',
        name: this.projectName,
        command: command,
        parameters: parameters,
        data: data
      }).then(function (message) {
        self.lastResult = message && message.value != null ? String(message.value) : '';
        return wantValue ? self.lastResult : undefined;
      }).catch(function (error) {
        self.lastResult = String(error && error.message || error);
        return wantValue ? self.lastResult : undefined;
      });
    }

    addCommand(args) {
      const self = this;
      const command = Scratch.Cast.toString(args.COMMAND);
      const name = Scratch.Cast.toString(args.NAME);
      if (!this.ready) {
        if (this.required) this.showRequired();
        this.lastResult = 'Python Bridge is not connected.';
        return;
      }
      this.showWaiting('Waiting for you to allow this command in the Python Bridge window.');
      return this.request({ t: 'add', command: command, name: name }).then(function (message) {
        self.hideOverlay();
        self.lastResult = message && message.ok ? 'allowed' : 'denied';
      }).catch(function (error) {
        self.hideOverlay();
        self.lastResult = String(error && error.message || error);
      });
    }

    getLastResult() {
      return this.lastResult;
    }

    showRequired() {
      const html = ''
        + '<div style="position:absolute;inset:0;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;font-family:sans-serif;">'
        + '<div style="max-width:440px;background:#161616;color:#fff;padding:22px 24px;border-radius:14px;text-align:center;line-height:1.45;">'
        + 'This Project Requires <a href="' + SITE + '" target="_blank" rel="noopener" style="color:#8ec5ff;">Python Bridge</a> (open source) running in your computer'
        + '</div></div>';
      this._show(html);
    }

    showWaiting(text) {
      const html = ''
        + '<div style="position:absolute;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;font-family:sans-serif;">'
        + '<div style="max-width:440px;background:#161616;color:#fff;padding:22px 24px;border-radius:14px;text-align:center;">'
        + text
        + '</div></div>';
      this._show(html);
    }

    _show(inner) {
      this.hideOverlay();
      const el = document.createElement('div');
      el.style.position = 'absolute';
      el.style.left = '0';
      el.style.top = '0';
      el.style.width = '100%';
      el.style.height = '100%';
      el.style.zIndex = '40';
      el.style.pointerEvents = 'auto';
      el.innerHTML = inner;
      const renderer = Scratch.vm && Scratch.vm.renderer;
      if (renderer && typeof renderer.addOverlay === 'function') {
        try { renderer.addOverlay(el, 'manual'); } catch (e) {}
      }
      if (!el.parentNode) {
        const canvas = renderer && renderer.canvas;
        const parent = canvas && canvas.parentElement;
        if (!parent) return;
        if (!parent.style.position) parent.style.position = 'relative';
        parent.appendChild(el);
      }
      this.overlay = el;
      this._blockInput();
    }

    _blockInput() {
      // Mouse and touch: the box covers only the stage, so stopping events on the box
      // keeps them away from the stage. The link inside the box still works.
      const self = this;
      const box = this.overlay;
      const pointerTypes = ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick',
        'wheel', 'touchstart', 'touchend', 'contextmenu'];
      const stopPointer = function (event) {
        if (event.target && event.target.closest && event.target.closest('a')) return;
        event.stopPropagation();
        event.preventDefault();
      };
      pointerTypes.forEach(function (type) { box.addEventListener(type, stopPointer); });

      // Keys: Scratch reads key presses for sensing, so block them while a box is up.
      // Typing in text fields (the code editor, inputs) keeps working.
      if (this._unblock) this._unblock();
      const keyTypes = ['keydown', 'keyup', 'keypress'];
      const stopKeys = function (event) {
        if (!self.overlay) return;
        const target = event.target;
        if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
        event.stopPropagation();
        event.preventDefault();
      };
      keyTypes.forEach(function (type) { document.addEventListener(type, stopKeys, true); });
      this._unblock = function () {
        keyTypes.forEach(function (type) { document.removeEventListener(type, stopKeys, true); });
        self._unblock = null;
      };
    }

    hideOverlay() {
      if (this.overlay && this.overlay.parentNode) this.overlay.parentNode.removeChild(this.overlay);
      this.overlay = null;
      if (this._unblock) this._unblock();
    }
  }

  Scratch.extensions.register(new PythonBridge());
})(Scratch);
