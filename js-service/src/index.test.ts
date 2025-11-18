import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { Request, Response } from 'express';

// Stub app.listen to avoid starting a real server
vi.mock('express', async (og) => {
  const mod: any = await og();
  const originalExpress = mod.default;
  const wrapped = () => {
    const app = originalExpress();
    app.listen = vi.fn(() => ({ close: vi.fn() }));
    return app;
  };
  return { ...mod, default: wrapped };
});

// Mock axios clients for external service calls
vi.mock('axios', () => {
  const clients = new Map<string, any>();
  const create = vi.fn((opts: any) => {
    const client = {
      request: vi.fn(),
      get: vi.fn(),
      defaults: { headers: {} },
    };
    clients.set(opts?.baseURL, client);
    return client;
  });
  const isAxiosError = (e: any) => Boolean(e && e.isAxiosError);
  return {
    default: { create, isAxiosError },
    create,
    isAxiosError,
    __clients: clients,
  };
});

import app from '../src/index';
import * as axiosModule from 'axios';

type Handler = (req: Request, res: Response, next?: Function) => any;

const getRouteHandler = (method: string, path: string): Handler => {
  const stack: any[] = (app as any)?._router?.stack ?? [];
  for (const layer of stack) {
    if (!layer.route) continue;
    if (layer.route.path === path && layer.route.methods?.[method.toLowerCase()]) {
      // return the first layer's handle
      return layer.route.stack[0].handle;
    }
  }
  throw new Error(`Route handler for ${method} ${path} not found`);
};

const getUseMiddlewares = (): Handler[] => {
  const stack: any[] = (app as any)?._router?.stack ?? [];
  return stack.filter((l) => !l.route && typeof l.handle === 'function').map((l) => l.handle);
};

const findNotFoundMiddleware = (): Handler => {
  const uses = getUseMiddlewares();
  // Find the last "use" middleware that takes (req, res) and send 404
  // The 404 handler is defined as app.use((req, res) => ...)
  // It has length 2
  for (let i = uses.length - 1; i >= 0; i--) {
    const fn = uses[i];
    if (fn.length === 2) {
      return fn;
    }
  }
  throw new Error('404 not found middleware not found');
};

const findErrorMiddleware = (): (err: Error, req: Request, res: Response, next: Function) => any => {
  const uses = getUseMiddlewares();
  // Error handler has signature (err, req, res, next) length === 4
  const errMw = uses.find((fn) => fn.length === 4);
  if (!errMw) throw new Error('Error handling middleware not found');
  return errMw as any;
};

const createMockRes = () => {
  const json = vi.fn();
  const status = vi.fn(() => ({ json }));
  const setHeader = vi.fn();
  const on = vi.fn();
  return {
    status,
    json,
    setHeader,
    on,
  } as unknown as Response;
};

const createMockReq = (overrides: Partial<Request> = {}) => {
  const base: Partial<Request> = {
    method: 'GET',
    path: '/',
    url: '/',
    headers: {},
    body: {},
    params: {},
    query: {},
  };
  return { ...base, ...overrides } as Request;
};

describe('API Gateway Routes', () => {
  let axiosClients: Map<string, any>;

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();

    axiosClients = (axiosModule as any).__clients as Map<string, any>;

    // Silence logs
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  test('GET / returns metadata', async () => {
    const handler = getRouteHandler('get', '/');
    const req = createMockReq({ method: 'GET', path: '/', url: '/' });
    const res = createMockRes();

    await handler(req, res);

    expect((res.status as any)).not.toHaveBeenCalled(); // defaults to 200
    expect((res.json as any)).toHaveBeenCalled();
    const body = (res.json as any).mock.calls[0][0];
    expect(body.service).toBe('API Gateway');
    expect(body.endpoints).toBeTruthy();
    expect(body.endpoints.go).toBe('/api/go/*');
  });

  test('GET /health/health returns healthy', async () => {
    const handler = getRouteHandler('get', '/health/health');
    const req = createMockReq({ method: 'GET', path: '/health/health', url: '/health/health' });
    const res = createMockRes();

    await handler(req, res);

    expect((res.json as any)).toHaveBeenCalled();
    const body = (res.json as any).mock.calls[0][0];
    expect(body.status).toBe('healthy');
    expect(body.service).toBe('api-gateway');
  });

  test('GET /health/status returns healthy when all services healthy', async () => {
    const handler = getRouteHandler('get', '/health/status');
    // mock health checks
    const go = axiosClients.get('http://go-service:8080');
    const py = axiosClients.get('http://python-service:8081');
    const rb = axiosClients.get('http://ruby-service:8082');
    go.get.mockResolvedValueOnce({ status: 200 });
    py.get.mockResolvedValueOnce({ status: 200 });
    rb.get.mockResolvedValueOnce({ status: 200 });

    const req = createMockReq({ method: 'GET', path: '/health/status', url: '/health/status' });
    const res = createMockRes();

    await handler(req, res);

    const body = (res.json as any).mock.calls[0][0];
    expect(body.status).toBe('healthy');
    expect(Array.isArray(body.services)).toBe(true);
    expect(body.services.every((s: any) => s.status === 'healthy')).toBe(true);
  });

  test('GET /health/status returns degraded when a service is unhealthy', async () => {
    const handler = getRouteHandler('get', '/health/status');
    const go = axiosClients.get('http://go-service:8080');
    const py = axiosClients.get('http://python-service:8081');
    const rb = axiosClients.get('http://ruby-service:8082');
    go.get.mockResolvedValueOnce({ status: 200 });
    py.get.mockRejectedValueOnce(new Error('down'));
    rb.get.mockResolvedValueOnce({ status: 200 });

    const req = createMockReq({ method: 'GET', path: '/health/status', url: '/health/status' });
    const res = createMockRes();

    await handler(req, res);

    const body = (res.json as any).mock.calls[0][0];
    expect(body.status).toBe('degraded');
    expect(body.services.some((s: any) => s.status === 'unhealthy')).toBe(true);
  });

  test('Proxy GET /api/go/* passes through and returns success', async () => {
    const handler = getRouteHandler('all', '/api/go/*');
    const go = axiosClients.get('http://go-service:8080');
    go.request.mockResolvedValueOnce({ data: { ok: true, svc: 'go' } });

    const req = createMockReq({
      method: 'GET',
      path: '/api/go/foo/bar',
      url: '/api/go/foo/bar?x=1',
      query: { x: '1' } as any,
      headers: { 'x-custom': 'abc' } as any,
    });
    const res = createMockRes();

    await handler(req, res);

    expect(go.request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'get',
        url: '/foo/bar',
        params: { x: '1' },
      })
    );
    const body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(true);
    expect(body.service).toBe('go');
    expect(body.data).toEqual({ ok: true, svc: 'go' });
  });

  test('Proxy POST /api/python/* sends body and returns success', async () => {
    const handler = getRouteHandler('all', '/api/python/*');
    const py = axiosClients.get('http://python-service:8081');
    py.request.mockResolvedValueOnce({ data: { created: true } });

    const req = createMockReq({
      method: 'POST',
      path: '/api/python/items',
      url: '/api/python/items',
      body: { name: 'Item1' } as any,
    });
    const res = createMockRes();

    await handler(req, res);

    expect(py.request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'post',
        url: '/items',
        data: { name: 'Item1' },
      })
    );
    const body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(true);
    expect(body.service).toBe('python');
  });

  test('Proxy PUT /api/ruby/* and DELETE /api/ruby/* handle methods', async () => {
    const handler = getRouteHandler('all', '/api/ruby/*');
    const rb = axiosClients.get('http://ruby-service:8082');

    // PUT
    rb.request.mockResolvedValueOnce({ data: { updated: true } });
    const putReq = createMockReq({
      method: 'PUT',
      path: '/api/ruby/users/123',
      url: '/api/ruby/users/123',
      body: { email: 'a@b.com' } as any,
    });
    let res = createMockRes();
    await handler(putReq, res);

    expect(rb.request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'put',
        url: '/users/123',
        data: { email: 'a@b.com' },
      })
    );
    let body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(true);

    // DELETE
    rb.request.mockResolvedValueOnce({ data: { deleted: true } });
    const delReq = createMockReq({
      method: 'DELETE',
      path: '/api/ruby/users/123',
      url: '/api/ruby/users/123',
    });
    res = createMockRes();
    await handler(delReq, res);

    expect(rb.request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'delete',
        url: '/users/123',
      })
    );
    body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(true);
  });

  test('Proxy handles upstream AxiosError with status and message', async () => {
    const handler = getRouteHandler('all', '/api/go/*');
    const go = axiosClients.get('http://go-service:8080');
    go.request.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 404, data: { reason: 'nope' } },
      message: 'Not Found',
    });

    const req = createMockReq({
      method: 'GET',
      path: '/api/go/unknown',
      url: '/api/go/unknown',
    });
    const res = createMockRes();

    await handler(req, res);

    expect((res.status as any)).toHaveBeenCalledWith(404);
    const body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(false);
    expect(body.error).toBe('Not Found');
  });

  test('Proxy handles non-Axios error as 500', async () => {
    const handler = getRouteHandler('all', '/api/python/*');
    const py = axiosClients.get('http://python-service:8081');
    py.request.mockRejectedValueOnce(new Error('Unexpected'));

    const req = createMockReq({
      method: 'GET',
      path: '/api/python/crash',
      url: '/api/python/crash',
    });
    const res = createMockRes();

    await handler(req, res);

    expect((res.status as any)).toHaveBeenCalledWith(500);
    const body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(false);
    expect(body.error).toBe('Unexpected');
  });

  test('404 middleware returns not found JSON', async () => {
    const notFoundMw = findNotFoundMiddleware();
    const req = createMockReq({
      method: 'GET',
      path: '/nope',
      url: '/nope',
    });
    const res = createMockRes();

    await notFoundMw(req, res);

    expect((res.status as any)).toHaveBeenCalledWith(404);
    const body = (res.json as any).mock.calls[0][0];
    expect(body.error).toContain('Route GET /nope not found');
  });

  test('Error handling middleware returns 500 with message', async () => {
    const errorMw = findErrorMiddleware();
    const req = createMockReq({ method: 'GET', path: '/err', url: '/err' });
    const res = createMockRes();
    const next = vi.fn();

    await (errorMw as any)(new Error('Boom'), req, res, next);

    expect((res.status as any)).toHaveBeenCalledWith(500);
    const body = (res.json as any).mock.calls[0][0];
    expect(body.success).toBe(false);
    expect(body.error).toBe('Boom');
  });

  test('Endpoints work without authentication headers (no auth required)', async () => {
    const handler = getRouteHandler('get', '/health/health');
    const req = createMockReq({ method: 'GET', path: '/health/health', url: '/health/health', headers: {} as any });
    const res = createMockRes();

    await handler(req, res);

    expect((res.json as any)).toHaveBeenCalled();
    const body = (res.json as any).mock.calls[0][0];
    expect(body.status).toBe('healthy');
  });
});
