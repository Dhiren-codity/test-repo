import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response } from 'express';

type Routes = {
  GET: Map<string, (req: Request, res: Response) => unknown>;
  POST: Map<string, (req: Request, res: Response) => unknown>;
  PUT: Map<string, (req: Request, res: Response) => unknown>;
  DELETE: Map<string, (req: Request, res: Response) => unknown>;
};

type AxiosGet = (url: string, config?: Record<string, unknown>) => Promise<{ status: number }>;

vi.mock('cors', () => {
  const middleware = (): ((..._args: unknown[]) => void) => {
    return (): void => {};
  };
  return {
    default: middleware,
  };
});

vi.mock('express', () => {
  const routes: Routes = {
    GET: new Map(),
    POST: new Map(),
    PUT: new Map(),
    DELETE: new Map(),
  };

  const register =
    (method: 'GET' | 'POST' | 'PUT' | 'DELETE') =>
    (path: string, handler: (req: Request, res: Response) => unknown): void => {
      routes[method].set(path, handler);
    };

  const app = {
    use: vi.fn((_mw: unknown): void => {}),
    get: register('GET'),
    post: register('POST'),
    put: register('PUT'),
    delete: register('DELETE'),
    listen: vi.fn((_port: number | string, _cb?: () => void): void => {}),
  };

  const expressFn = (): typeof app => app;

  const json = (): ((..._args: unknown[]) => void) => {
    return (_req: unknown, _res: unknown, next?: () => void): void => {
      if (typeof next === 'function') {
        next();
      }
    };
  };

  return {
    default: expressFn,
    json,
    __routes: routes,
    __app: app,
  };
});

vi.mock('axios', () => {
  const get: AxiosGet = vi.fn(async (): Promise<{ status: number }> => {
    return { status: 200 };
  });
  return {
    default: { get },
  };
});

describe('js-service API routes', () => {
  let routes: Routes;

  const getRoutes = async (): Promise<Routes> => {
    const expressModule = await import('express');
    const r = (expressModule as unknown as { __routes: Routes }).__routes;
    return r;
  };

  const importApp = async (): Promise<void> => {
    await import('../src/index');
  };

  const createMockRes = (): {
    res: Partial<Response>;
    statusMock: ReturnType<typeof vi.fn>;
    jsonMock: ReturnType<typeof vi.fn>;
  } => {
    const jsonMock = vi.fn((_body: unknown): void => {});
    const resObj: Partial<Response> = {};
    const statusMock = vi.fn((_code: number): Partial<Response> => {
      return resObj;
    });
    Object.assign(resObj, {
      status: statusMock,
      json: jsonMock,
    });
    return { res: resObj, statusMock, jsonMock };
  };

  const invoke = async (
    method: keyof Routes,
    path: string,
    reqInit: Partial<Request> = {}
  ): Promise<{ statusMock: ReturnType<typeof vi.fn>; jsonMock: ReturnType<typeof vi.fn> }> => {
    const handler = routes[method].get(path);
    if (!handler) {
      throw new Error(`Handler for ${method} ${path} not registered`);
    }
    const { res, statusMock, jsonMock } = createMockRes();
    const req: Partial<Request> = {
      body: {},
      params: {},
      query: {},
      ...reqInit,
    };

    await Promise.resolve(handler(req as Request, res as Response) as unknown as Promise<unknown>);
    return { statusMock, jsonMock };
  };

  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    process.env.GO_SERVICE_URL = 'http://localhost:8080';
    process.env.PYTHON_SERVICE_URL = 'http://localhost:8081';
    process.env.RUBY_SERVICE_URL = 'http://localhost:8082';
    routes = await getRoutes();
    await importApp();
  });

  afterEach((): void => {
    vi.clearAllMocks();
  });

  test('GET /health returns healthy status', async () => {
    const { statusMock, jsonMock } = await invoke('GET', '/health');
    expect(statusMock).not.toHaveBeenCalled();
    expect(jsonMock).toHaveBeenCalledTimes(1);
    expect(jsonMock.mock.calls[0]?.[0]).toEqual({ status: 'healthy', service: 'js-cache' });
  });

  test('GET /cache/stats returns empty stats initially', async () => {
    const { jsonMock } = await invoke('GET', '/cache/stats');
    const payload = jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(typeof payload.timestamp).toBe('string');
    expect(payload.totalServices).toBe(0);
    expect(payload.cacheStats).toEqual([]);
  });

  test('POST /cache/record validation: missing service returns 400', async () => {
    const { statusMock, jsonMock } = await invoke('POST', '/cache/record', {
      body: { key: 'k1', hit: true },
    });
    expect(statusMock).toHaveBeenCalledWith(400);
    expect(jsonMock).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/record hit increments stats; GET /cache/stats reflects values', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'go', hit: true } });
    const stats1 = await invoke('GET', '/cache/stats');
    const payload1 = stats1.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const cacheStats1 = payload1.cacheStats as Array<Record<string, unknown>>;
    expect(cacheStats1.length).toBe(1);
    expect(cacheStats1[0]?.service).toBe('go');
    expect(cacheStats1[0]?.hits).toBe(1);
    expect(cacheStats1[0]?.misses).toBe(0);
    expect(cacheStats1[0]?.size).toBe(0);
    expect(cacheStats1[0]?.hitRate).toBe('100.00%');

    await invoke('POST', '/cache/record', { body: { service: 'go', hit: false, key: 'k1' } });
    const stats2 = await invoke('GET', '/cache/stats');
    const payload2 = stats2.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const cacheStats2 = payload2.cacheStats as Array<Record<string, unknown>>;
    expect(cacheStats2[0]?.hits).toBe(1);
    expect(cacheStats2[0]?.misses).toBe(1);
    expect(cacheStats2[0]?.size).toBe(1);
    expect(cacheStats2[0]?.hitRate).toBe('50.00%');
  });

  test('POST /cache/record miss without key increases misses but not size', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'python', hit: false } });
    const stats = await invoke('GET', '/cache/stats');
    const payload = stats.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const cacheStats = payload.cacheStats as Array<Record<string, unknown>>;
    const py = cacheStats.find((s) => s.service === 'python') as Record<string, unknown>;
    expect(py.hits).toBe(0);
    expect(py.misses).toBe(1);
    expect(py.size).toBe(0);
    expect(py.hitRate).toBe('0.00%');
  });

  test('POST /cache/invalidate validation: missing service returns 400', async () => {
    const { statusMock, jsonMock } = await invoke('POST', '/cache/invalidate', { body: {} });
    expect(statusMock).toHaveBeenCalledWith(400);
    expect(jsonMock).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/invalidate returns 404 if cache for service not found', async () => {
    const { statusMock, jsonMock } = await invoke('POST', '/cache/invalidate', {
      body: { service: 'nonexistent', key: 'k1' },
    });
    expect(statusMock).toHaveBeenCalledWith(404);
    expect(jsonMock).toHaveBeenCalledWith({ error: "Cache for service 'nonexistent' not found" });
  });

  test('POST /cache/invalidate with key removes only that entry and responds with remaining count', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'ruby', hit: false, key: 'a' } });
    await invoke('POST', '/cache/record', { body: { service: 'ruby', hit: false, key: 'b' } });

    const invalidateRes = await invoke('POST', '/cache/invalidate', {
      body: { service: 'ruby', key: 'a' },
    });
    const payload = invalidateRes.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.message).toBe("Cache key 'a' invalidated for service 'ruby'");
    expect(payload.remainingEntries).toBe(1);

    const stats = await invoke('GET', '/cache/stats');
    const sPayload = stats.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const cacheStats = sPayload.cacheStats as Array<Record<string, unknown>>;
    const ruby = cacheStats.find((s) => s.service === 'ruby') as Record<string, unknown>;
    expect(ruby.size).toBe(1);
  });

  test('POST /cache/invalidate without key clears all entries and resets hits/misses', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'go', hit: false, key: 'k1' } });
    await invoke('POST', '/cache/record', { body: { service: 'go', hit: true } });
    await invoke('POST', '/cache/record', { body: { service: 'go', hit: false, key: 'k2' } });

    const invalidateAllForService = await invoke('POST', '/cache/invalidate', {
      body: { service: 'go' },
    });
    const payload = invalidateAllForService.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload).toEqual({ message: "All cache cleared for service 'go'" });

    const stats = await invoke('GET', '/cache/stats');
    const sPayload = stats.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const cacheStats = sPayload.cacheStats as Array<Record<string, unknown>>;
    const go = cacheStats.find((s) => s.service === 'go') as Record<string, unknown>;
    expect(go.hits).toBe(0);
    expect(go.misses).toBe(0);
    expect(go.size).toBe(0);
  });

  test('POST /cache/invalidate with non-existent key keeps remainingEntries unchanged', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'python', hit: false, key: 'only' } });

    const res1 = await invoke('POST', '/cache/invalidate', {
      body: { service: 'python', key: 'missing' },
    });
    const payload1 = res1.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload1.message).toBe("Cache key 'missing' invalidated for service 'python'");
    expect(payload1.remainingEntries).toBe(1);
  });

  test('POST /cache/invalidate-all clears all services cache', async () => {
    await invoke('POST', '/cache/record', { body: { service: 'go', hit: false, key: 'k' } });
    await invoke('POST', '/cache/record', { body: { service: 'python', hit: false, key: 'p' } });
    await invoke('POST', '/cache/record', { body: { service: 'ruby', hit: false, key: 'r' } });

    const res = await invoke('POST', '/cache/invalidate-all', { body: {} });
    const payload = res.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(typeof payload.timestamp).toBe('string');
    expect(payload.message).toBe('All caches cleared across all services');

    const stats = await invoke('GET', '/cache/stats');
    const sPayload = stats.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(sPayload.totalServices).toBe(0);
    expect(sPayload.cacheStats).toEqual([]);
  });

  test('GET /cache/services marks services online/offline based on axios responses', async () => {
    const axiosModule = await import('axios');
    const axiosDefault = axiosModule.default as unknown as { get: AxiosGet };
    (axiosDefault.get as unknown as ReturnType<typeof vi.fn>).mockImplementationOnce(async (_url: string): Promise<{ status: number }> => ({ status: 200 }))
      .mockImplementationOnce(async (_url: string): Promise<{ status: number }> => {
        throw new Error('offline');
      })
      .mockImplementationOnce(async (_url: string): Promise<{ status: number }> => {
        throw new Error('offline');
      });

    const res = await invoke('GET', '/cache/services');
    const payload = res.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const services = payload.services as Array<Record<string, unknown>>;
    expect(services).toEqual([
      { name: 'go', status: 'online', port: 8080, cacheEnabled: false },
      { name: 'python', status: 'offline', port: 8081, cacheEnabled: false },
      { name: 'ruby', status: 'offline', port: 8082, cacheEnabled: false },
    ]);
    expect(typeof payload.timestamp).toBe('string');
  });

  test('GET /cache/services shows cacheEnabled true when service cache exists', async () => {
    const axiosModule = await import('axios');
    const axiosDefault = axiosModule.default as unknown as { get: AxiosGet };
    (axiosDefault.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 200 });

    await invoke('POST', '/cache/record', { body: { service: 'go', hit: true } });

    const res = await invoke('GET', '/cache/services');
    const payload = res.jsonMock.mock.calls[0]?.[0] as Record<string, unknown>;
    const services = payload.services as Array<Record<string, unknown>>;
    const go = services.find((s) => s.name === 'go') as Record<string, unknown>;
    const py = services.find((s) => s.name === 'python') as Record<string, unknown>;
    const rb = services.find((s) => s.name === 'ruby') as Record<string, unknown>;
    expect(go.cacheEnabled).toBe(true);
    expect(py.cacheEnabled).toBe(false);
    expect(rb.cacheEnabled).toBe(false);
  });

  test('No PUT or DELETE routes are registered', async () => {
    expect(routes.PUT.size).toBe(0);
    expect(routes.DELETE.size).toBe(0);
  });
});
