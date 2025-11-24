import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response } from 'express';

type Handler = (req: Request, res: Response) => unknown;
type Routes = {
  get: Map<string, Handler>;
  post: Map<string, Handler>;
  put: Map<string, Handler>;
  delete: Map<string, Handler>;
};

vi.mock('cors', () => {
  const corsMock = vi.fn(() => {
    return (_req: unknown, _res: unknown, next: () => void): void => next();
  });
  return { default: corsMock };
});

vi.mock('express', () => {
  const routeRegistry: Routes = {
    get: new Map<string, Handler>(),
    post: new Map<string, Handler>(),
    put: new Map<string, Handler>(),
    delete: new Map<string, Handler>(),
  };

  const app = {
    use: vi.fn(),
    get: vi.fn((path: string, handler: Handler): void => {
      routeRegistry.get.set(path, handler);
    }),
    post: vi.fn((path: string, handler: Handler): void => {
      routeRegistry.post.set(path, handler);
    }),
    put: vi.fn((path: string, handler: Handler): void => {
      routeRegistry.put.set(path, handler);
    }),
    delete: vi.fn((path: string, handler: Handler): void => {
      routeRegistry.delete.set(path, handler);
    }),
    listen: vi.fn((_port: unknown, callback?: () => void) => {
      if (typeof callback === 'function') {
        callback();
      }
      return { close: vi.fn() };
    }),
  };

  const mockExpress = vi.fn(() => app) as unknown as {
    (): typeof app;
    json: () => (req: unknown, res: unknown, next: () => void) => void;
  };

  mockExpress.json = vi.fn(() => {
    return (_req: unknown, _res: unknown, next: () => void): void => next();
  });

  const reset = (): void => {
    routeRegistry.get.clear();
    routeRegistry.post.clear();
    routeRegistry.put.clear();
    routeRegistry.delete.clear();
    app.use.mockClear();
    app.get.mockClear();
    app.post.mockClear();
    app.put.mockClear();
    app.delete.mockClear();
    app.listen.mockClear();
    mockExpress.mockClear();
    mockExpress.json.mockClear();
  };

  const getRoutes = (): Routes => routeRegistry;

  return {
    default: mockExpress,
    __getRoutes: getRoutes,
    __reset: reset,
  };
});

vi.mock('axios', () => {
  const get = vi.fn();
  return {
    default: { get },
  };
});

const createMockRes = (): { res: Response; statusMock: ReturnType<typeof vi.fn>; jsonMock: ReturnType<typeof vi.fn> } => {
  const jsonMock = vi.fn();
  const statusMock = vi.fn((_code?: number) => ({ json: jsonMock }));
  const resPartial: Partial<Response> = {
    status: statusMock as unknown as Response['status'],
    json: jsonMock as unknown as Response['json'],
  };
  return {
    res: resPartial as Response,
    statusMock,
    jsonMock,
  };
};

const createMockReq = (overrides?: Partial<Request>): Request => {
  const base: Partial<Request> = {
    body: {},
    params: {},
    query: {},
    method: 'GET',
    url: '',
    headers: {},
  };
  return { ...base, ...(overrides ?? {}) } as Request;
};

const invoke = async (handler: Handler, req: Request, res: Response): Promise<void> => {
  await Promise.resolve(handler(req, res));
};

describe('js-service API routes', () => {
  let routes: Routes;

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();

    const expressMock = await import('express') as unknown as { __reset: () => void; __getRoutes: () => Routes };
    expressMock.__reset();

    await import('../src/index');
    routes = expressMock.__getRoutes();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test('GET /health returns service health', async () => {
    const handler = routes.get.get('/health');
    expect(typeof handler).toBe('function');

    const { res, statusMock, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'GET', url: '/health' });

    await invoke(handler as Handler, req, res);

    expect(statusMock).not.toHaveBeenCalled();
    expect(jsonMock).toHaveBeenCalledWith({ status: 'healthy', service: 'js-cache' });
  });

  test('GET /cache/stats returns empty stats when no services', async () => {
    const handler = routes.get.get('/cache/stats');
    expect(typeof handler).toBe('function');

    const { res, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'GET', url: '/cache/stats' });

    await invoke(handler as Handler, req, res);

    const bodyArg = jsonMock.mock.calls[0]?.[0] as { cacheStats: unknown[]; totalServices: number; timestamp: string };
    expect(Array.isArray(bodyArg.cacheStats)).toBe(true);
    expect(bodyArg.totalServices).toBe(0);
    expect(typeof bodyArg.timestamp).toBe('string');
  });

  test('POST /cache/record returns 400 when service missing', async () => {
    const handler = routes.post.get('/cache/record');
    expect(typeof handler).toBe('function');

    const { res, statusMock, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'POST', url: '/cache/record', body: {} });

    await invoke(handler as Handler, req, res);

    expect(statusMock).toHaveBeenCalledWith(400);
    expect(jsonMock).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/record records hits and misses; GET /cache/stats reflects counts and size', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const statsHandler = routes.get.get('/cache/stats') as Handler;

    const recordReq1 = createMockReq({ method: 'POST', url: '/cache/record', body: { service: 'go', hit: true } });
    const recordReq2 = createMockReq({ method: 'POST', url: '/cache/record', body: { service: 'go', hit: true } });
    const recordReq3 = createMockReq({ method: 'POST', url: '/cache/record', body: { service: 'go', hit: false, key: 'k1' } });

    const res1 = createMockRes();
    const res2 = createMockRes();
    const res3 = createMockRes();

    await invoke(recordHandler, recordReq1, res1.res);
    await invoke(recordHandler, recordReq2, res2.res);
    await invoke(recordHandler, recordReq3, res3.res);

    const { res: statsRes, jsonMock: statsJson } = createMockRes();
    const statsReq = createMockReq({ method: 'GET', url: '/cache/stats' });
    await invoke(statsHandler, statsReq, statsRes);

    const body = statsJson.mock.calls[0]?.[0] as { cacheStats: Array<{ service: string; hits: number; misses: number; size: number; hitRate: string }>; totalServices: number; timestamp: string };
    const goStats = body.cacheStats.find(s => s.service === 'go');
    expect(goStats).toBeTruthy();
    expect(goStats?.hits).toBe(2);
    expect(goStats?.misses).toBe(1);
    expect(goStats?.size).toBe(1);
    expect(goStats?.hitRate).toBe('66.67%');
    expect(body.totalServices).toBe(1);
    expect(typeof body.timestamp).toBe('string');
  });

  test('POST /cache/invalidate returns 400 when service missing', async () => {
    const handler = routes.post.get('/cache/invalidate');
    expect(typeof handler).toBe('function');

    const { res, statusMock, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'POST', url: '/cache/invalidate', body: {} });

    await invoke(handler as Handler, req, res);

    expect(statusMock).toHaveBeenCalledWith(400);
    expect(jsonMock).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/invalidate returns 404 when cache for service not found', async () => {
    const handler = routes.post.get('/cache/invalidate');
    expect(typeof handler).toBe('function');

    const { res, statusMock, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'POST', url: '/cache/invalidate', body: { service: 'unknown' } });

    await invoke(handler as Handler, req, res);

    expect(statusMock).toHaveBeenCalledWith(404);
    expect(jsonMock).toHaveBeenCalledWith({ error: "Cache for service 'unknown' not found" });
  });

  test('POST /cache/invalidate with key removes specific entry and returns remaining size', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const invalidateHandler = routes.post.get('/cache/invalidate') as Handler;

    // Prepare cache with two entries for 'python'
    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'python', hit: false, key: 'key1' } }), createMockRes().res);
    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'python', hit: false, key: 'key2' } }), createMockRes().res);

    const { res, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'POST', url: '/cache/invalidate', body: { service: 'python', key: 'key1' } });

    await invoke(invalidateHandler, req, res);

    const responseBody = jsonMock.mock.calls[0]?.[0] as { message: string; remainingEntries: number };
    expect(responseBody.message).toBe("Cache key 'key1' invalidated for service 'python'");
    expect(responseBody.remainingEntries).toBe(1);
  });

  test('POST /cache/invalidate with non-existent key still returns message and size unchanged', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const invalidateHandler = routes.post.get('/cache/invalidate') as Handler;

    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'ruby', hit: false, key: 'exists' } }), createMockRes().res);

    const { res, jsonMock } = createMockRes();
    const req = createMockReq({ method: 'POST', url: '/cache/invalidate', body: { service: 'ruby', key: 'missing' } });

    await invoke(invalidateHandler, req, res);

    const responseBody = jsonMock.mock.calls[0]?.[0] as { message: string; remainingEntries: number };
    expect(responseBody.message).toBe("Cache key 'missing' invalidated for service 'ruby'");
    expect(responseBody.remainingEntries).toBe(1);
  });

  test('POST /cache/invalidate without key clears service cache and resets hit/miss', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const invalidateHandler = routes.post.get('/cache/invalidate') as Handler;
    const statsHandler = routes.get.get('/cache/stats') as Handler;

    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'go', hit: true } }), createMockRes().res);
    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'go', hit: false, key: 'abc' } }), createMockRes().res);

    const invRes = createMockRes();
    await invoke(invalidateHandler, createMockReq({ method: 'POST', body: { service: 'go' } }), invRes.res);

    const statsRes = createMockRes();
    await invoke(statsHandler, createMockReq({ method: 'GET' }), statsRes.res);

    const body = statsRes.jsonMock.mock.calls[0]?.[0] as { cacheStats: Array<{ service: string; hits: number; misses: number; size: number }> };
    const goStats = body.cacheStats.find(s => s.service === 'go');
    expect(goStats?.hits).toBe(0);
    expect(goStats?.misses).toBe(0);
    expect(goStats?.size).toBe(0);
  });

  test('POST /cache/invalidate-all clears all services caches', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const invalidateAllHandler = routes.post.get('/cache/invalidate-all') as Handler;
    const statsHandler = routes.get.get('/cache/stats') as Handler;

    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'go', hit: false, key: 'k1' } }), createMockRes().res);
    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'python', hit: false, key: 'k2' } }), createMockRes().res);

    const invAllRes = createMockRes();
    await invoke(invalidateAllHandler, createMockReq({ method: 'POST' }), invAllRes.res);

    const statsRes = createMockRes();
    await invoke(statsHandler, createMockReq({ method: 'GET' }), statsRes.res);
    const body = statsRes.jsonMock.mock.calls[0]?.[0] as { cacheStats: unknown[]; totalServices: number };
    expect(Array.isArray(body.cacheStats)).toBe(true);
    expect(body.totalServices).toBe(0);
  });

  test('GET /cache/services reports online/offline and cacheEnabled based on axios and cache state', async () => {
    const recordHandler = routes.post.get('/cache/record') as Handler;
    const servicesHandler = routes.get.get('/cache/services') as Handler;

    // Create cache entries for 'go' only so cacheEnabled is true for go and false otherwise
    await invoke(recordHandler, createMockReq({ method: 'POST', body: { service: 'go', hit: false, key: 'svc' } }), createMockRes().res);

    const axios = (await import('axios')).default as unknown as { get: ReturnType<typeof vi.fn> };
    axios.get.mockImplementation(async (url: unknown): Promise<unknown> => {
      if (typeof url === 'string' && url.includes('8080')) {
        return { status: 200 };
      }
      throw new Error('offline');
    });

    const { res, jsonMock } = createMockRes();
    await invoke(servicesHandler, createMockReq({ method: 'GET', url: '/cache/services' }), res);

    const body = jsonMock.mock.calls[0]?.[0] as { services: Array<{ name: string; status: string; port: number; cacheEnabled: boolean }>; timestamp: string };
    const go = body.services.find(s => s.name === 'go');
    const py = body.services.find(s => s.name === 'python');
    const rb = body.services.find(s => s.name === 'ruby');

    expect(go?.status).toBe('online');
    expect(go?.cacheEnabled).toBe(true);

    expect(py?.status).toBe('offline');
    expect(py?.cacheEnabled).toBe(false);

    expect(rb?.status).toBe('offline');
    expect(rb?.cacheEnabled).toBe(false);

    expect(typeof body.timestamp).toBe('string');
  });

  test('Unsupported methods (PUT/DELETE) are not registered', async () => {
    expect(routes.put.size).toBe(0);
    expect(routes.delete.size).toBe(0);
    expect(routes.put.get('/health')).toBeUndefined();
    expect(routes.delete.get('/cache/record')).toBeUndefined();
  });
});
