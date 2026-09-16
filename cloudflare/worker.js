/**
 * DreamDash 在线房间中继（Cloudflare Worker + Durable Object）
 *
 * 一个房间 = 一个 Durable Object 实例，所以房主与客机必定落在同一个对象里，
 * 房间内消息直接互转，不需要任何全局状态。
 *
 * 路由：
 *   GET /ws?room=XXXX&role=host|guest   WebSocket 中继
 *   GET /version                        供客户端探测（返回 { server: 'cloud' }）
 */

const MAX_MESSAGE_BYTES = 256 * 1024;
const ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

function normalizeRoom(value) {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8);
}

function peerTag(role) {
  return role === 'guest' ? 'host' : 'guest';
}

export class Room {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const upgrade = (request.headers.get('Upgrade') || '').toLowerCase();
    if (upgrade !== 'websocket') {
      return new Response('expected websocket', { status: 426 });
    }

    const url = new URL(request.url);
    const role = url.searchParams.get('role') === 'guest' ? 'guest' : 'host';
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];

    // 同一个角色重复连接时，踢掉旧连接，保证「一台机器一个身份」
    for (const socket of this.ctx.getWebSockets(role)) {
      try {
        socket.send(JSON.stringify({ t: 'error', message: '该身份已在别处连接' }));
        socket.close(4001, 'replaced');
      } catch (error) {
        /* ignore */
      }
    }

    this.ctx.acceptWebSocket(server, [role]);
    server.send(JSON.stringify({
      t: 'welcome',
      role,
      room: normalizeRoom(url.searchParams.get('room')),
      version: this.env.BUILD_VERSION || 'cloud',
      server: 'cloud'
    }));

    const peer = this.ctx.getWebSockets(peerTag(role))[0];
    if (peer) {
      peer.send(JSON.stringify({ t: 'peer-joined', role }));
    }

    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(socket, message) {
    if (typeof message !== 'string') return;           // 只处理文本协议
    if (message.length > MAX_MESSAGE_BYTES) {
      socket.close(1009, 'message too large');
      return;
    }
    for (const tag of socket.tags) {
      const peer = this.ctx.getWebSockets(peerTag(tag))[0];
      if (peer) {
        try {
          peer.send(message);
        } catch (error) {
          /* 对端已断开，忽略 */
        }
      }
    }
  }

  async webSocketClose(socket) {
    for (const tag of socket.tags) {
      const peer = this.ctx.getWebSockets(peerTag(tag))[0];
      if (peer) {
        try {
          peer.send(JSON.stringify({ t: 'peer-left', role: tag }));
        } catch (error) {
          /* ignore */
        }
      }
    }
    try {
      socket.close(1000, 'closed');
    } catch (error) {
      /* ignore */
    }
  }

  async webSocketError(socket) {
    await this.webSocketClose(socket);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/version') {
      const body = JSON.stringify({
        server: 'cloud',
        version: env.BUILD_VERSION || 'cloud',
        rooms: true
      });
      return new Response(body, {
        headers: {
          'content-type': 'application/json; charset=utf-8',
          'access-control-allow-origin': '*',
          'cache-control': 'no-store'
        }
      });
    }

    if (url.pathname === '/ws') {
      const room = normalizeRoom(url.searchParams.get('room'));
      const role = url.searchParams.get('role') === 'guest' ? 'guest' : 'host';
      if (!room) {
        return new Response('missing room code', { status: 400 });
      }
      const id = env.ROOMS.idFromName(room);
      const stub = env.ROOMS.get(id);
      const target = new URL(request.url);
      target.searchParams.set('room', room);
      target.searchParams.set('role', role);
      return stub.fetch(new Request(target.toString(), request));
    }

    if (url.pathname === '/' || url.pathname === '') {
      return new Response('DreamDash relay online. Use /ws?room=CODE&role=host', {
        headers: { 'content-type': 'text/plain; charset=utf-8' }
      });
    }

    return new Response('not found', { status: 404 });
  }
};

export { ROOM_ALPHABET };
