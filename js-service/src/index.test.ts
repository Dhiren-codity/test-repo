import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response } from 'express';
import axios from 'axios';

type Handler = (req: Request, res: Response) => unknown | Promise<unknown>;

interface RegisteredRoute {
  method: 'get' | 'post' | 'put' | 'delete';
  path: string;
  handler: Handler;
}

interface FakeApp {
  use: (mw: unknown) => void;
  get: (path: string, handler: Handler) => void;
  post: (path: string, handler: Handler) => void;
  put: (path: string, handler: Handler) => void;
  delete: (path: string, handler: Handler) => void;
  listen: (port: number | string, cb?: () => void) => void;
  routes: RegisteredRoute[];
}

type JsonFn = (body: unknown) => unknown;
type StatusFn = (code: number) => { json: JsonFn };

vi.mock('cors', () => {
  return {
    default: vi.fn(() => {
      return (_req: unknown, _res: unknown, next: () => void): void => {
        next();
      };
    }),
  };
});

vi.mock('axios', () => {
  const get = vi.fn();
  return {
    default: { get },
    get,
  };
});

vi.mock('express', () => {
  let lastApp: FakeApp | null = null;

  const createApp = (): FakeApp => {
    const routes: RegisteredRoute[] = [];
    const app: FakeApp = {
      use: vi.fn((_mw: unknown): void => {}),
      get: vi.fn((path: string, handler: Handler): void => {
        routes.push({ method: 'get', path, handler });
      }),
      post: vi.fn((path: string, handler: Handler): void => {
        routes.push({ method: 'post', path, handler });
      }),
      put: vi.fn((path: string, handler: Handler): void => {
        routes.push({ method: 'put', path, handler });
      }),
      delete: vi.fn((path: string, handler: Handler): void => {
        routes.push({ method: 'delete', path, handler });
      }),
      listen: vi.fn((_port: number | string, cb?: () => void): void => {
        if (cb) cb();
      }),
      routes,
    };
    return app;
  };

  const express = (): FakeApp => {
    lastApp = createApp();
    return lastApp;
  };
  (express as unknown as Record<string, unknown>).json = vi.fn(() => {
    return (_req: unknown, _res: unknown, next: () => void): void => {
      next();
    };
  });

  const getLastApp = (): FakeApp => {
    if (!lastApp) {
      throw new Error('App not created');
    }
    return lastApp;
  };

  return {
    default: express,
    getLastApp,
  };
});

const { getLastApp } = await import('express');

type MockRes = {
  status: StatusFn;
  json: JsonFn;
  statusCode: number;
  body: unknown;
};

const createMockReq = (overrides?: Partial<Request>): Request => {
  const base: Partial<Request> = {
    body: {},
    params: {},
    query: {},
    headers: {},
  };
  return { ...base, ...(overrides ?? {}) } as Request;
};

const createMockRes = (): Response & MockRes => {
  let currentStatus = 200;
  let currentBody: unknown;
  const json: JsonFn = vi.fn((body: unknown) => {
    currentBody = body;
    return undefined;
  });
  const status: StatusFn = vi.fn((code: number) => {
    currentStatus = code;
    return { json };
  });
  const res: Partial<Response> = {
    status,
    json,
  };
  return Object.assign(res, {
    status,
    json,
    statusCode: currentStatus,
    get body(): unknown {
      return currentBody;
    },
    set body(_val: unknown) {
      currentBody = _val;
    },
  }) as Response & MockRes;
};

const findRoute = (app: FakeApp, method: 'get' | 'post' | 'put' | 'delete', path: string): Handler | undefined => {
  const route = app.routes.find((r) => r.method === method && r.path === path);
  return route?.handler;
};

const loadApp = async (): Promise<FakeApp> => {
  await import('../../js-service/src/index.ts');
  return getLastApp();
};

describe('js-service API routes', () => {
  beforeEach(async (): Promise<void> => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  afterEach((): void => {
    vi.clearAllMocks();
  });

  test('GET /health returns healthy status', async (): Promise<void> => {
    const app = await loadApp();
    const handler = findRoute(app, 'get', '/health');
    expect(handler).toBeDefined();

    const req = createMockReq();
    const res = createMockRes();

    await handler!(req, res);

    expect(res.status).not.toHaveBeenCalled();
    expect(res.json).toHaveBeenCalledWith({ status: 'healthy', service: 'js-cache' });
  });

  test('GET /cache/stats returns empty stats initially', async (): Promise<void> => {
    const app = await loadApp();
    const handler = findRoute(app, 'get', '/cache/stats');
    expect(handler).toBeDefined();

    const req = createMockReq();
    const res = createMockRes();

    await handler!(req, res);

    expect(res.json).toHaveBeenCalled();
    const body = (res.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    expect(body.cacheStats).toEqual([]);
    expect(body.totalServices).toBe(0);
    expect(typeof body.timestamp).toBe('string');
  });

  test('POST /cache/record returns 400 when service missing', async (): Promise<void> => {
    const app = await loadApp();
    const handler = findRoute(app, 'post', '/cache/record');
    expect(handler).toBeDefined();

    const req = createMockReq({ body: {} });
    const res = createMockRes();

    await handler!(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/record increments hits/misses and creates entries; GET /cache/stats reflects values', async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const stats = findRoute(app, 'get', '/cache/stats');
    expect(record).toBeDefined();
    expect(stats).toBeDefined();

    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'svcA', hit: true } }), res1);
    await record!(createMockReq({ body: { service: 'svcA', hit: true } }), res1);
    await record!(createMockReq({ body: { service: 'svcA', hit: true } }), res1);
    await record!(createMockReq({ body: { service: 'svcA', hit: false, key: 'k1' } }), res1);
    await record!(createMockReq({ body: { service: 'svcA', hit: false, key: 'k2' } }), res1);

    const res2 = createMockRes();
    await stats!(createMockReq(), res2);

    const body = (res2.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    const cacheStats = body.cacheStats as Array<Record<string, unknown>>;
    const svcA = cacheStats.find((s) => s.service === 'svcA') as Record<string, unknown> | undefined;
    expect(svcA).toBeDefined();
    expect(svcA?.hits).toBe(3);
    expect(svcA?.misses).toBe(2);
    expect(svcA?.size).toBe(2);
    expect(svcA?.hitRate).toBe('60.00%');
  });

  test('POST /cache/invalidate returns 400 without service', async (): Promise<void> => {
    const app = await loadApp();
    const handler = findRoute(app, 'post', '/cache/invalidate');
    expect(handler).toBeDefined();

    const res = createMockRes();
    await handler!(createMockReq({ body: {} }), res);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith({ error: 'Service name required' });
  });

  test('POST /cache/invalidate returns 404 if service cache missing', async (): Promise<void> => {
    const app = await loadApp();
    const handler = findRoute(app, 'post', '/cache/invalidate');
    expect(handler).toBeDefined();

    const res = createMockRes();
    await handler!(createMockReq({ body: { service: 'unknown' } }), res);

    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith({ error: "Cache for service 'unknown' not found" });
  });

  test("POST /cache/invalidate with 'key' removes only that entry", async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const invalidate = findRoute(app, 'post', '/cache/invalidate');
    expect(record).toBeDefined();
    expect(invalidate).toBeDefined();

    const res1 = createMockRes();
    // Create misses with keys
    await record!(createMockReq({ body: { service: 'svcKey', hit: false, key: 'one' } }), res1);
    await record!(createMockReq({ body: { service: 'svcKey', hit: false, key: 'two' } }), res1);

    const res2 = createMockRes();
    await invalidate!(createMockReq({ body: { service: 'svcKey', key: 'one' } }), res2);

    expect(res2.json).toHaveBeenCalledWith({
      message: "Cache key 'one' invalidated for service 'svcKey'",
      remainingEntries: 1,
    });
  });

  test("POST /cache/invalidate without 'key' clears all entries and resets counters", async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const invalidate = findRoute(app, 'post', '/cache/invalidate');
    const stats = findRoute(app, 'get', '/cache/stats');
    expect(record).toBeDefined();
    expect(invalidate).toBeDefined();
    expect(stats).toBeDefined();

    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'svcClear', hit: true } }), res1);
    await record!(createMockReq({ body: { service: 'svcClear', hit: false, key: 'x' } }), res1);

    const res2 = createMockRes();
    await invalidate!(createMockReq({ body: { service: 'svcClear' } }), res2);

    expect(res2.json).toHaveBeenCalledWith({
      message: "All cache cleared for service 'svcClear'",
    });

    const res3 = createMockRes();
    await stats!(createMockReq(), res3);
    const body = (res3.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    const svcStats = (body.cacheStats as Array<Record<string, unknown>>).find((s) => s.service === 'svcClear') as
      | Record<string, unknown>
      | undefined;

    // If service remains tracked after clearing, it should have zeroed counters and size 0.
    if (svcStats) {
      expect(svcStats.hits).toBe(0);
      expect(svcStats.misses).toBe(0);
      expect(svcStats.size).toBe(0);
    }
  });

  test('POST /cache/invalidate-all clears caches for all services', async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const invalidateAll = findRoute(app, 'post', '/cache/invalidate-all');
    const stats = findRoute(app, 'get', '/cache/stats');
    expect(record).toBeDefined();
    expect(invalidateAll).toBeDefined();
    expect(stats).toBeDefined();

    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'svc1', hit: false, key: 'a' } }), res1);
    await record!(createMockReq({ body: { service: 'svc2', hit: true } }), res1);

    const res2 = createMockRes();
    await invalidateAll!(createMockReq(), res2);
    expect(res2.json).toHaveBeenCalled();
    const body2 = (res2.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    expect(body2.message).toBe('All caches cleared across all services');

    const res3 = createMockRes();
    await stats!(createMockReq(), res3);
    const body3 = (res3.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    expect(body3.totalServices).toBe(0);
    expect(body3.cacheStats).toEqual([]);
  });

  test('GET /cache/services reports statuses and cacheEnabled using mocked axios', async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const services = findRoute(app, 'get', '/cache/services');
    expect(record).toBeDefined();
    expect(services).toBeDefined();

    // Create cache for 'go' service only
    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'go', hit: true } }), res1);

    const axiosDefault = axios as unknown as { get: ReturnType<typeof vi.fn> };
    axiosDefault.get
      .mockResolvedValueOnce({ status: 200, data: { status: 'healthy' } }) // go
      .mockRejectedValueOnce(new Error('network')) // python
      .mockResolvedValueOnce({ status: 200, data: { status: 'healthy' } }); // ruby

    const res2 = createMockRes();
    await services!(createMockReq(), res2);

    const body = (res2.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    const list = body.services as Array<Record<string, unknown>>;
    expect(list).toHaveLength(3);

    const go = list.find((s) => s.name === 'go') as Record<string, unknown>;
    const py = list.find((s) => s.name === 'python') as Record<string, unknown>;
    const rb = list.find((s) => s.name === 'ruby') as Record<string, unknown>;

    expect(go.status).toBe('online');
    expect(go.cacheEnabled).toBe(true);

    expect(py.status).toBe('offline');
    expect(py.cacheEnabled).toBe(false);

    expect(rb.status).toBe('online');
    expect(rb.cacheEnabled).toBe(false);
  });

  test('Non-existent methods (PUT/DELETE) are not registered for /cache/record', async (): Promise<void> => {
    const app = await loadApp();
    const putHandler = findRoute(app, 'put', '/cache/record');
    const deleteHandler = findRoute(app, 'delete', '/cache/record');

    expect(putHandler).toBeUndefined();
    expect(deleteHandler).toBeUndefined();
  });

  test('GET /cache/stats returns 0.00% hitRate for new service after clear', async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const invalidate = findRoute(app, 'post', '/cache/invalidate');
    const stats = findRoute(app, 'get', '/cache/stats');

    expect(record).toBeDefined();
    expect(invalidate).toBeDefined();
    expect(stats).toBeDefined();

    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'zero', hit: false, key: 'k' } }), res1);

    const res2 = createMockRes();
    await invalidate!(createMockReq({ body: { service: 'zero' } }), res2);

    const res3 = createMockRes();
    await stats!(createMockReq(), res3);

    const body = (res3.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    const stat = (body.cacheStats as Array<Record<string, unknown>>).find((s) => s.service === 'zero') as
      | Record<string, unknown>
      | undefined;

    if (stat) {
      expect(stat.hitRate).toBe('0.00%');
      expect(stat.size).toBe(0);
      expect(stat.hits).toBe(0);
      expect(stat.misses).toBe(0);
    }
  });

  test('POST /cache/record with miss but no key should not create entry', async (): Promise<void> => {
    const app = await loadApp();
    const record = findRoute(app, 'post', '/cache/record');
    const stats = findRoute(app, 'get', '/cache/stats');
    expect(record).toBeDefined();
    expect(stats).toBeDefined();

    const res1 = createMockRes();
    await record!(createMockReq({ body: { service: 'svcNoKey', hit: false } }), res1);

    const res2 = createMockRes();
    await stats!(createMockReq(), res2);
    const body = (res2.json as unknown as vi.Mock).mock.calls[0][0] as Record<string, unknown>;
    const svc = (body.cacheStats as Array<Record<string, unknown>>).find((s) => s.service === 'svcNoKey') as
      | Record<string, unknown>
      | undefined;

    expect(svc).toBeDefined();
    if (svc) {
      expect(svc.size).toBe(0);
      expect(svc.misses).toBe(1);
      expect(svc.hits).toBe(0);
      expect(svc.hitRate).toBe('0.00%');
    }
  });
});
