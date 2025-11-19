import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response, Express } from 'express';
import * as http from 'node:http';

type AxiosClientMock = {
  request: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
  defaults: { headers: Record<string, string> };
};

// Global axios client mocks created in order: go, python, ruby
let axiosClientMocks: AxiosClientMock[] = [];

// Mock dotenv to avoid reading actual env
vi.mock('dotenv', () => ({
  default: {
    config: vi.fn(),
  },
}));

// No-op security and rate limit middlewares
vi.mock('helmet', () => ({
  default: () => (req: any, res: any, next: any) => next(),
}));
vi.mock('cors', () => ({
  default: () => (req: any, res: any, next: any) => next(),
}));
vi.mock('express-rate-limit', () => ({
  default: () => (req: any, res: any, next: any) => next(),
}));

// Axios mock with create returning distinct clients
vi.mock('axios', () => {
  const create = vi.fn(() => {
    const client: AxiosClientMock = {
      request: vi.fn(),
      get: vi.fn(),
      defaults: { headers: { 'Content-Type': 'application/json' } },
    };
    axiosClientMocks.push(client);
    return client as any;
  });
  const isAxiosError = (err: any) => Boolean(err && err.isAxiosError);
  return {
    default: { create, isAxiosError },
    create,
    isAxiosError,
  };
});

function createMockReq(partial: Partial<Request> = {}): Partial<Request> {
  const defaultReq: Partial<Request> = {
    method: 'GET',
    path: '/',
    url: '/',
    headers: {},
    body: {},
    params: {},
    query: {},
  };
  return { ...defaultReq, ...partial };
}

function createMockRes(): {
  res: Partial<Response>;
  jsonMock: ReturnType<typeof vi.fn>;
  statusMock: ReturnType<typeof vi.fn>;
  endMock: ReturnType<typeof vi.fn>;
  setHeaderMock: ReturnType<typeof vi.fn>;
} {
  const jsonMock = vi.fn();
  const endMock = vi.fn();
  const setHeaderMock = vi.fn();
  const statusMock = vi.fn(() => ({ json: jsonMock, end: endMock, setHeader: setHeaderMock }));
  const res: Partial<Response> = {
    status: statusMock as any,
    json: jsonMock as any,
    end: endMock as any,
    setHeader: setHeaderMock as any,
  };
  return { res, jsonMock, statusMock, endMock, setHeaderMock };
}

async function setupApp() {
  // Prevent the server from actually listening
  const listenSpy = vi.spyOn(http.Server.prototype, 'listen').mockImplementation(function (this: any) {
    // emulate Node's Server.listen returning the server instance
    return this;
  } as any);
  // Reset axios client mocks
  axiosClientMocks = [];

  // Set env to deterministic values
  process.env.PORT = '0';
  process.env.NODE_ENV = 'test';
  process.env.GO_SERVICE_URL = 'http://go-service:8080';
  process.env.PYTHON_SERVICE_URL = 'http://python-service:8081';
  process.env.RUBY_SERVICE_URL = 'http://ruby-service:8082';

  const mod = await import('./index');
  const app = (mod.default || mod) as Express;

  return { app, listenSpy };
}

function findRouteHandler(app: Express, path: string, method?: string) {
  // @ts-ignore access private router
  const stack = app._router?.stack || [];
  for (const layer of stack) {
    if (layer?.route && layer.route.path === path) {
      // Optionally ensure method is supported
      if (method) {
        const methods = layer.route.methods || {};
        if (!methods[method.toLowerCase()]) {
          continue;
        }
      }
      const handles = layer.route.stack || [];
      if (handles.length > 0) {
        return handles[0].handle;
      }
    }
  }
  throw new Error(`Route handler for ${method || 'any'} ${path} not found`);
}

function findMiddlewareByArity(app: Express, arity: number) {
  // @ts-ignore
  const stack = app._router?.stack || [];
  return stack
    .map((l: any) => l?.handle)
    .filter((h: any) => h && h.length === arity);
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('API Gateway Routes', () => {
  test('GET / should return gateway info', async () => {
    const { app } = await setupApp();

    const handler = findRouteHandler(app, '/', 'get');
    const req = createMockReq({ method: 'GET', path: '/', url: '/' }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    expect(jsonMock).toHaveBeenCalledTimes(1);
    const payload = jsonMock.mock.calls[0][0];
    expect(payload).toHaveProperty('service', 'API Gateway');
    expect(payload).toHaveProperty('endpoints');
    expect(payload.endpoints).toHaveProperty('go', '/api/go/*');
  });

  test('GET /health/health should return healthy status', async () => {
    const { app } = await setupApp();

    const handler = findRouteHandler(app, '/health/health', 'get');
    const req = createMockReq({ method: 'GET', path: '/health/health', url: '/health/health' }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);
    const payload = jsonMock.mock.calls[0][0];

    expect(payload).toHaveProperty('status', 'healthy');
    expect(payload).toHaveProperty('service', 'api-gateway');
    expect(typeof payload.timestamp).toBe('string');
  });

  test('GET /health/status should aggregate healthy services', async () => {
    const { app } = await setupApp();

    // go, python, ruby clients should exist and their get('/health') should resolve
    axiosClientMocks.forEach((client) => {
      client.get.mockResolvedValue({ data: { status: 'ok' } });
    });

    const handler = findRouteHandler(app, '/health/status', 'get');
    const req = createMockReq({ method: 'GET', path: '/health/status', url: '/health/status' }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.status).toBe('healthy');
    expect(payload.gateway.status).toBe('healthy');
    expect(Array.isArray(payload.services)).toBe(true);
    expect(payload.services.length).toBe(3);
    expect(payload.services.every((s: any) => s.status === 'healthy')).toBe(true);
  });

  test('GET /health/status should return degraded when a service is unhealthy', async () => {
    const { app } = await setupApp();

    // go healthy, python healthy, ruby unhealthy
    axiosClientMocks[0].get.mockResolvedValue({ data: { status: 'ok' } });
    axiosClientMocks[1].get.mockResolvedValue({ data: { status: 'ok' } });
    axiosClientMocks[2].get.mockRejectedValue(new Error('Down'));

    const handler = findRouteHandler(app, '/health/status', 'get');
    const req = createMockReq({ method: 'GET', path: '/health/status', url: '/health/status' }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.status).toBe('degraded');
    expect(payload.services.length).toBe(3);
    expect(payload.services.some((s: any) => s.status === 'unhealthy')).toBe(true);
  });

  test('GET /api/go/* should proxy GET requests and include headers', async () => {
    const { app } = await setupApp();

    // Arrange client for 'go' (first created)
    axiosClientMocks[0].request.mockResolvedValue({ data: { result: 'ok' } });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'GET',
      path: '/api/go/users',
      url: '/api/go/users',
      headers: { 'x-test': 'abc' },
      query: { q: 'john' },
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    await handler(req, res as Response);

    expect(statusMock).not.toHaveBeenCalled(); // default 200
    expect(axiosClientMocks[0].request).toHaveBeenCalledTimes(1);
    const callArgs = axiosClientMocks[0].request.mock.calls[0][0];
    expect(callArgs.method).toBe('get');
    // Based on the current regex implementation, this will be '/'
    expect(callArgs.url).toBe('/');
    expect(callArgs.headers['x-test']).toBe('abc');

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(true);
    expect(payload.service).toBe('go');
    expect(payload.data).toEqual({ result: 'ok' });
  });

  test('POST /api/go/* should proxy body and method', async () => {
    const { app } = await setupApp();

    axiosClientMocks[0].request.mockResolvedValue({ data: { created: true } });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'POST',
      path: '/api/go/items',
      url: '/api/go/items',
      headers: { 'content-type': 'application/json' },
      body: { name: 'Item' },
    }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    const callArgs = axiosClientMocks[0].request.mock.calls[0][0];
    expect(callArgs.method).toBe('post');
    expect(callArgs.data).toEqual({ name: 'Item' });

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(true);
  });

  test('PUT /api/go/* should proxy', async () => {
    const { app } = await setupApp();

    axiosClientMocks[0].request.mockResolvedValue({ data: { updated: true } });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'PUT',
      path: '/api/go/items/1',
      url: '/api/go/items/1',
      body: { name: 'Updated' },
    }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    const callArgs = axiosClientMocks[0].request.mock.calls[0][0];
    expect(callArgs.method).toBe('put');
    expect(callArgs.data).toEqual({ name: 'Updated' });

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(true);
  });

  test('DELETE /api/go/* should proxy', async () => {
    const { app } = await setupApp();

    axiosClientMocks[0].request.mockResolvedValue({ data: { deleted: true } });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'DELETE',
      path: '/api/go/items/1',
      url: '/api/go/items/1',
    }) as Request;
    const { res, jsonMock } = createMockRes();

    await handler(req, res as Response);

    const callArgs = axiosClientMocks[0].request.mock.calls[0][0];
    expect(callArgs.method).toBe('delete');

    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(true);
  });

  test('Proxy error handling: downstream returns 404', async () => {
    const { app } = await setupApp();

    axiosClientMocks[0].request.mockRejectedValue({
      isAxiosError: true,
      message: 'Not Found',
      response: { status: 404, data: { error: 'not found' } },
    });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'GET',
      path: '/api/go/missing',
      url: '/api/go/missing',
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    await handler(req, res as Response);

    expect(statusMock).toHaveBeenCalledWith(404);
    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('Not Found');
    expect(payload.service).toBe('go');
  });

  test('Proxy error handling: network error -> 500', async () => {
    const { app } = await setupApp();

    axiosClientMocks[0].request.mockRejectedValue({
      isAxiosError: true,
      message: 'ECONNREFUSED',
    });

    const handler = findRouteHandler(app, '/api/go/*');
    const req = createMockReq({
      method: 'GET',
      path: '/api/go/any',
      url: '/api/go/any',
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    await handler(req, res as Response);

    expect(statusMock).toHaveBeenCalledWith(500);
    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('ECONNREFUSED');
  });

  test('Python and Ruby proxy routes should use respective clients', async () => {
    const { app } = await setupApp();

    // Arrange python (2nd) and ruby (3rd)
    axiosClientMocks[1].request.mockResolvedValue({ data: { py: true } });
    axiosClientMocks[2].request.mockResolvedValue({ data: { rb: true } });

    const pyHandler = findRouteHandler(app, '/api/python/*');
    const rbHandler = findRouteHandler(app, '/api/ruby/*');

    const pyReq = createMockReq({
      method: 'POST',
      path: '/api/python/do',
      url: '/api/python/do',
      body: { a: 1 },
    }) as Request;
    const rbReq = createMockReq({
      method: 'GET',
      path: '/api/ruby/info',
      url: '/api/ruby/info',
    }) as Request;

    const pyRes = createMockRes();
    const rbRes = createMockRes();

    await pyHandler(pyReq, pyRes.res as Response);
    await rbHandler(rbReq, rbRes.res as Response);

    expect(axiosClientMocks[1].request).toHaveBeenCalledTimes(1);
    expect(axiosClientMocks[2].request).toHaveBeenCalledTimes(1);
    expect(pyRes.jsonMock).toHaveBeenCalledWith(expect.objectContaining({ success: true, data: { py: true }, service: 'python' }));
    expect(rbRes.jsonMock).toHaveBeenCalledWith(expect.objectContaining({ success: true, data: { rb: true }, service: 'ruby' }));
  });

  test('404 middleware returns not found for unknown route', async () => {
    const { app } = await setupApp();

    const notFoundMiddlewares = findMiddlewareByArity(app, 2); // (req, res) signature
    // Use the first 2-arity middleware which should be the 404 handler before the error handler
    const notFound = notFoundMiddlewares[0];

    const req = createMockReq({
      method: 'GET',
      path: '/does-not-exist',
      url: '/does-not-exist',
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    await notFound(req, res as Response);

    expect(statusMock).toHaveBeenCalledWith(404);
    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(false);
    expect(payload.error).toContain('Route GET /does-not-exist not found');
  });

  test('No authentication required for health endpoint (if present)', async () => {
    const { app } = await setupApp();

    const handler = findRouteHandler(app, '/health/health', 'get');
    const req = createMockReq({
      method: 'GET',
      path: '/health/health',
      url: '/health/health',
      headers: {}, // no Authorization header
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    await handler(req, res as Response);

    expect(statusMock).not.toHaveBeenCalledWith(401);
    const payload = jsonMock.mock.calls[0][0];
    expect(payload.status).toBe('healthy');
  });
});
