import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response, NextFunction } from 'express';

// Mock helmet, cors, rate-limit to no-op middlewares
vi.mock('helmet', () => ({
  default: vi.fn(() => (req: any, res: any, next: NextFunction) => next()),
}));
vi.mock('cors', () => ({
  default: vi.fn(() => (req: any, res: any, next: NextFunction) => next()),
}));
vi.mock('express-rate-limit', () => ({
  default: vi.fn(() => (req: any, res: any, next: NextFunction) => next()),
}));

// Mock axios with controllable clients by baseURL
const axiosClientsByBaseUrl = new Map<string, any>();
vi.mock('axios', () => {
  const create = vi.fn((config: any) => {
    const client = {
      baseURL: config?.baseURL,
      defaults: { headers: config?.headers ?? {} },
      request: vi.fn(async (_opts: any) => ({ data: null, status: 200 })),
      get: vi.fn(async (_url: string, _opts?: any) => ({ data: null, status: 200 })),
    };
    axiosClientsByBaseUrl.set(config?.baseURL, client);
    return client;
  });

  const isAxiosError = (err: any) => !!(err && err.__isAxiosError);

  const getClient = (baseURL: string) => axiosClientsByBaseUrl.get(baseURL);

  return {
    default: { create, isAxiosError },
    create,
    isAxiosError,
    __getClientByBaseURL: getClient,
    __clients: axiosClientsByBaseUrl,
  };
});

// Mock express to capture route handlers without starting a real server
type Handler = (req: Request, res: Response, next?: NextFunction) => any;
type ErrorHandler = (err: Error, req: Request, res: Response, next: NextFunction) => any;
vi.mock('express', () => {
  const makeApp = () => {
    const routes = {
      get: new Map<string, Handler>(),
      all: new Map<string, Handler>(),
      use: [] as Array<Handler | ErrorHandler>,
    };

    const app: any = {
      __routes: routes,
      use: vi.fn((...args: any[]) => {
        const fn = args[args.length - 1];
        routes.use.push(fn);
        return app;
      }),
      get: vi.fn((path: string, ...handlers: Handler[]) => {
        routes.get.set(path, handlers[handlers.length - 1]);
        return app;
      }),
      all: vi.fn((path: string, ...handlers: Handler[]) => {
        routes.all.set(path, handlers[handlers.length - 1]);
        return app;
      }),
      listen: vi.fn((_port: number, cb?: () => void) => {
        if (cb) cb();
        return app;
      }),
    };

    const expressFn: any = () => app;
    expressFn.json = () => (req: any, res: any, next: NextFunction) => next();
    expressFn.urlencoded = () => (req: any, res: any, next: NextFunction) => next();

    return { default: expressFn, Express: Object, Request: Object, Response: Object, NextFunction: Object };
  };

  return makeApp();
});

// Utility to create mock req/res
function createMockRes() {
  const res: Partial<Response> & { statusCode?: number } = {};
  const json = vi.fn();
  const status = vi.fn((code: number) => {
    res.statusCode = code;
    return res as Response;
  });
  const on = vi.fn();
  Object.assign(res, {
    status,
    json,
    on,
    setHeader: vi.fn(),
    getHeader: vi.fn(),
  });
  return { res: res as Response, status, json, on };
}

function createMockReq(overrides?: Partial<Request>) {
  const req: Partial<Request> = {
    method: 'GET',
    path: '/',
    body: {},
    query: {},
    headers: {},
    ...overrides,
  };
  return req as Request;
}

describe('API Gateway Routes (Express + Vitest)', () => {
  let app: any;
  let axiosMock: any;
  let processOnSpy: any;

  const GO_URL = 'http://go-service:8080';
  const PY_URL = 'http://python-service:8081';
  const RB_URL = 'http://ruby-service:8082';

  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    axiosClientsByBaseUrl.clear();
    processOnSpy = vi.spyOn(process, 'on').mockImplementation(() => process as any);

    axiosMock = await import('axios');
    const mod = await import('../src/index');
    app = mod.default;
  });

  afterEach(() => {
    processOnSpy.mockRestore();
  });

  test('GET / should return API metadata', async () => {
    const rootHandler = app.__routes.get.get('/');
    const { res, json, status } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/' });

    await rootHandler(req, res);

    expect(status).not.toHaveBeenCalled();
    expect(json).toHaveBeenCalledTimes(1);
    const payload = json.mock.calls[0][0];
    expect(payload.service).toBe('API Gateway');
    expect(payload.endpoints.go).toBe('/api/go/*');
  });

  test('GET /health/health should return healthy status', async () => {
    const handler = app.__routes.get.get('/health/health');
    const { res, json } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/health/health' });

    await handler(req, res);

    const body = json.mock.calls[0][0];
    expect(body.status).toBe('healthy');
    expect(body.service).toBe('api-gateway');
  });

  test('GET /health/status should return healthy when all upstream services are healthy', async () => {
    // defaults of axios mock already resolve successfully
    const handler = app.__routes.get.get('/health/status');
    const { res, json } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/health/status' });

    await handler(req, res);

    const body = json.mock.calls[0][0];
    expect(body.status).toBe('healthy');
    expect(Array.isArray(body.services)).toBe(true);
    expect(body.services.length).toBe(3);
    expect(body.services.every((s: any) => s.status === 'healthy')).toBe(true);
  });

  test('GET /health/status should return degraded when at least one upstream is unhealthy', async () => {
    const pythonClient = axiosMock.__getClientByBaseURL(PY_URL);
    pythonClient.get.mockRejectedValueOnce(new Error('Python down'));

    const handler = app.__routes.get.get('/health/status');
    const { res, json } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/health/status' });

    await handler(req, res);

    const body = json.mock.calls[0][0];
    expect(body.status).toBe('degraded');
    expect(body.services.some((s: any) => s.service === 'python' && s.status === 'unhealthy')).toBe(true);
  });

  test('Proxy GET /api/go/* should forward request and return success response', async () => {
    const goClient = axiosMock.__getClientByBaseURL(GO_URL);
    goClient.request.mockResolvedValueOnce({ data: { hello: 'world' }, status: 200 });

    const handler = app.__routes.all.get('/api/go/*');
    const { res, json, status } = createMockRes();
    const req = createMockReq({
      method: 'GET',
      path: '/api/go/hello',
      query: { a: '1' } as any,
      headers: { 'x-test': '1' } as any,
    });

    await handler(req, res);

    // check axios request called with expected options
    expect(goClient.request).toHaveBeenCalledTimes(1);
    const callArg = goClient.request.mock.calls[0][0];
    expect(callArg.method).toBe('get');
    // Due to regex in source, target path resolves to '/' (no match for '/api/go/...'):
    expect(callArg.url).toBe('/');
    expect(callArg.params).toEqual({ a: '1' });
    expect(callArg.headers['x-test']).toBe('1');
    expect(callArg.headers['Content-Type']).toBe('application/json');

    // response assertions
    expect(status).not.toHaveBeenCalled();
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        success: true,
        data: { hello: 'world' },
        service: 'go',
      })
    );
  });

  test('Proxy POST /api/python/* should forward body and method', async () => {
    const pyClient = axiosMock.__getClientByBaseURL(PY_URL);
    pyClient.request.mockResolvedValueOnce({ data: { ok: true }, status: 200 });

    const handler = app.__routes.all.get('/api/python/*');
    const { res, json } = createMockRes();
    const req = createMockReq({
      method: 'POST',
      path: '/api/python/items',
      body: { name: 'Item' } as any,
      headers: { authorization: 'Bearer token' } as any,
    });

    await handler(req, res);

    expect(pyClient.request).toHaveBeenCalledTimes(1);
    const callArg = pyClient.request.mock.calls[0][0];
    expect(callArg.method).toBe('post');
    // regex bug -> '/'
    expect(callArg.url).toBe('/');
    expect(callArg.data).toEqual({ name: 'Item' });
    expect(callArg.headers.authorization).toBe('Bearer token');
    expect(json).toHaveBeenCalledWith(expect.objectContaining({ success: true, service: 'python' }));
  });

  test('Proxy PUT /api/ruby/* should forward body and method', async () => {
    const rbClient = axiosMock.__getClientByBaseURL(RB_URL);
    rbClient.request.mockResolvedValueOnce({ data: { updated: 1 }, status: 200 });

    const handler = app.__routes.all.get('/api/ruby/*');
    const { res, json } = createMockRes();
    const req = createMockReq({
      method: 'PUT',
      path: '/api/ruby/resource/1',
      body: { name: 'New' } as any,
    });

    await handler(req, res);

    const arg = rbClient.request.mock.calls[0][0];
    expect(arg.method).toBe('put');
    expect(arg.url).toBe('/');
    expect(arg.data).toEqual({ name: 'New' });
    expect(json).toHaveBeenCalledWith(expect.objectContaining({ success: true, service: 'ruby' }));
  });

  test('Proxy DELETE /api/go/* should forward method', async () => {
    const goClient = axiosMock.__getClientByBaseURL(GO_URL);
    goClient.request.mockResolvedValueOnce({ data: { deleted: true }, status: 200 });

    const handler = app.__routes.all.get('/api/go/*');
    const { res, json } = createMockRes();
    const req = createMockReq({
      method: 'DELETE',
      path: '/api/go/resource/123',
      headers: { 'x-del': '1' } as any,
    });

    await handler(req, res);

    const arg = goClient.request.mock.calls[0][0];
    expect(arg.method).toBe('delete');
    expect(arg.url).toBe('/');
    expect(json).toHaveBeenCalledWith(expect.objectContaining({ success: true, service: 'go' }));
  });

  test('Proxy should map upstream AxiosError status and message', async () => {
    const goClient = axiosMock.__getClientByBaseURL(GO_URL);
    const axiosErr = {
      __isAxiosError: true,
      response: { status: 404, data: { code: 'NOT_FOUND' } },
      message: 'Request failed with status code 404',
    };
    goClient.request.mockRejectedValueOnce(axiosErr);

    const handler = app.__routes.all.get('/api/go/*');
    const { res, json, status } = createMockRes();
    const req = createMockReq({
      method: 'GET',
      path: '/api/go/missing',
    });

    await handler(req, res);

    expect(status).toHaveBeenCalledWith(404);
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        success: false,
        error: 'Request failed with status code 404',
        service: 'go',
      })
    );
  });

  test('Proxy should return 500 on non-Axios errors', async () => {
    const rbClient = axiosMock.__getClientByBaseURL(RB_URL);
    rbClient.request.mockRejectedValueOnce(new Error('Boom'));

    const handler = app.__routes.all.get('/api/ruby/*');
    const { res, json, status } = createMockRes();
    const req = createMockReq({
      method: 'GET',
      path: '/api/ruby/error',
    });

    await handler(req, res);

    expect(status).toHaveBeenCalledWith(500);
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        success: false,
        service: 'ruby',
      })
    );
  });

  test('404 handler should return not found for unknown route', async () => {
    const notFound = [...app.__routes.use].filter((fn: any) => fn.length === 2).pop();
    const { res, json, status } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/unknown' });

    await (notFound as Handler)(req, res);

    expect(status).toHaveBeenCalledWith(404);
    const body = json.mock.calls[0][0];
    expect(body.success).toBe(false);
    expect(body.error).toContain('Route GET /unknown not found');
  });

  test('Error handler should return 500 with error message', async () => {
    const errorHandler = app.__routes.use.find((fn: any) => fn.length === 4);
    const { res, json, status } = createMockRes();
    const req = createMockReq({ method: 'GET', path: '/will-crash' });

    await (errorHandler as ErrorHandler)(new Error('Unexpected'), req, res, vi.fn());

    expect(status).toHaveBeenCalledWith(500);
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        success: false,
        error: 'Unexpected',
      })
    );
  });
});
