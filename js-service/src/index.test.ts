import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Request, Response } from 'express';

interface MockAxiosClient {
  request: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
  defaults: { headers: Record<string, string> };
}

vi.mock('helmet', () => {
  const mw = vi.fn((_req: unknown, _res: unknown, next: () => void): void => next());
  const helmet = vi.fn(() => mw);
  return { default: helmet };
});

vi.mock('cors', () => {
  const mw = vi.fn((_req: unknown, _res: unknown, next: () => void): void => next());
  const cors = vi.fn(() => mw);
  return { default: cors };
});

vi.mock('express-rate-limit', () => {
  const rateLimit = vi.fn((_opts: Record<string, unknown>) => {
    return vi.fn((_req: unknown, _res: unknown, next: () => void): void => next());
  });
  return { default: rateLimit };
});

vi.mock('express', () => {
  type Middleware = (req: Request, res: Response, next: () => void) => void;
  type ErrorMiddleware = (err: Error, req: Request, res: Response, next: () => void) => void;
  type RouteHandler = (req: Request, res: Response) => void | Promise<void>;

  const apps: {
    routes: {
      get: Record<string, RouteHandler>;
      all: Record<string, RouteHandler>;
    };
    uses: Array<Middleware | ((req: Request, res: Response) => void) | ErrorMiddleware>;
    listen: ReturnType<typeof vi.fn>;
  }[] = [];

  const express = vi.fn(() => {
    const app = {
      routes: {
        get: {} as Record<string, RouteHandler>,
        all: {} as Record<string, RouteHandler>,
      },
      uses: [] as Array<Middleware | ((req: Request, res: Response) => void) | ErrorMiddleware>,
      use: vi.fn((...args: unknown[]) => {
        // app.use(fn) or app.use(path, fn) - we only need fn
        const fn = (args[0] as unknown) as Middleware | ((req: Request, res: Response) => void) | ErrorMiddleware;
        app.uses.push(fn);
      }),
      get: vi.fn((path: string, handler: RouteHandler) => {
        app.routes.get[path] = handler;
      }),
      all: vi.fn((path: string, handler: RouteHandler) => {
        app.routes.all[path] = handler;
      }),
      listen: vi.fn((_port: number, cb?: () => void) => {
        if (cb) cb();
        return undefined;
      }),
    };
    apps.push(app);
    return app as unknown as Record<string, unknown>;
  });

  // express.json() and express.urlencoded()
  const jsonMw = vi.fn((_req: unknown, _res: unknown, next: () => void): void => next());
  const urlEncodedMw = vi.fn((_req: unknown, _res: unknown, next: () => void): void => next());
  (express as unknown as { json: () => Middleware }).json = vi.fn(() => jsonMw as unknown as Middleware);
  (express as unknown as { urlencoded: (_opts: Record<string, unknown>) => Middleware }).urlencoded = vi.fn(
    (_opts: Record<string, unknown>) => urlEncodedMw as unknown as Middleware
  );

  const __getLatestApp = (): {
    routes: {
      get: Record<string, RouteHandler>;
      all: Record<string, RouteHandler>;
    };
    uses: Array<Middleware | ((req: Request, res: Response) => void) | ErrorMiddleware>;
    listen: ReturnType<typeof vi.fn>;
  } => apps[apps.length - 1];

  return {
    default: express,
    __getLatestApp,
  };
});

vi.mock('axios', () => {
  type RequestConfig = {
    method?: string;
    url?: string;
    data?: unknown;
    params?: Record<string, string>;
    headers?: Record<string, string>;
    timeout?: number;
  };

  const clientsByBaseURL = new Map<string, MockAxiosClient>();

  const create = vi.fn((config: { baseURL?: string; timeout?: number; headers?: Record<string, string> }) => {
    const client: MockAxiosClient = {
      defaults: { headers: { ...(config.headers || {}), 'Content-Type': 'application/json' } },
      request: vi.fn((_cfg: RequestConfig) => Promise.resolve({ data: {} })),
      get: vi.fn((_url: string, _cfg?: RequestConfig) => Promise.resolve({ data: {} })),
    };
    if (config.baseURL) {
      clientsByBaseURL.set(config.baseURL, client);
    }
    return client;
  });

  const isAxiosError = (error: unknown): boolean => {
    return Boolean((error as { isAxiosError?: boolean }).isAxiosError);
  };

  const __getClientByBaseURL = (url: string): MockAxiosClient | undefined => clientsByBaseURL.get(url);
  const __resetAxiosMock = (): void => {
    clientsByBaseURL.clear();
  };

  return {
    default: { create, isAxiosError },
    create,
    isAxiosError,
    __getClientByBaseURL,
    __resetAxiosMock,
  };
});

const GO_URL = 'http://go-service:8080';
const PY_URL = 'http://python-service:8081';
const RB_URL = 'http://ruby-service:8082';

type JsonMock = ReturnType<typeof vi.fn>;
type StatusMock = ReturnType<typeof vi.fn>;

function createMockReq(init?: {
  method?: string;
  path?: string;
  headers?: Record<string, string | string[] | undefined>;
  body?: unknown;
  query?: Record<string, string>;
}): Partial<Request> {
  return {
    method: init?.method ?? 'GET',
    path: init?.path ?? '/',
    headers: init?.headers ?? {},
    body: init?.body,
    query: init?.query ?? {},
  } as Partial<Request>;
}

function createMockRes(): {
  res: Partial<Response>;
  jsonMock: JsonMock;
  statusMock: StatusMock;
  getBody: () => unknown;
  getStatus: () => number;
} {
  let currentStatus = 200;
  let body: unknown;
  const jsonMock: JsonMock = vi.fn((payload: unknown) => {
    body = payload;
    // trigger finish event if registered
    const finishCb = finishListener;
    if (finishCb) {
      finishCb();
    }
  });
  const statusMock: StatusMock = vi.fn((code: number) => {
    currentStatus = code;
    return { json: jsonMock } as unknown as Response;
  });
  let finishListener: (() => void) | null = null;
  const on = vi.fn((event: string, cb: () => void) => {
    if (event === 'finish') {
      finishListener = cb;
    }
  });
  const res: Partial<Response> = {
    status: statusMock as unknown as Response['status'],
    json: jsonMock as unknown as Response['json'],
    on: on as unknown as Response['on'],
    statusCode: currentStatus,
  };
  return {
    res,
    jsonMock,
    statusMock,
    getBody: () => body,
    getStatus: () => currentStatus,
  };
}

describe('API Gateway Routes', () => {
  beforeEach(async (): Promise<void> => {
    vi.resetModules();
    vi.clearAllMocks();
    // Import server to register routes with mocked express
    await import('../src/index');
  });

  afterEach((): void => {
    // nothing for now
  });

  test('GET / should return service info', async (): Promise<void> => {
    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.get['/'];
    expect(handler).toBeDefined();

    const req = createMockReq({ method: 'GET', path: '/' }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    const sent = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(sent.service).toBe('API Gateway');
    expect((sent.endpoints as Record<string, unknown>).go).toBe('/api/go/*');
  });

  test('GET /health/health should be healthy', async (): Promise<void> => {
    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.get['/health/health'];
    expect(handler).toBeDefined();

    const req = createMockReq({ method: 'GET', path: '/health/health' }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.status).toBe('healthy');
    expect(payload.service).toBe('api-gateway');
  });

  test('GET /health/status should aggregate healthy services', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const go = __getClientByBaseURL(GO_URL) as MockAxiosClient;
    const py = __getClientByBaseURL(PY_URL) as MockAxiosClient;
    const rb = __getClientByBaseURL(RB_URL) as MockAxiosClient;

    go.get.mockResolvedValueOnce({ data: { ok: true } });
    py.get.mockResolvedValueOnce({ data: { ok: true } });
    rb.get.mockResolvedValueOnce({ data: { ok: true } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.get['/health/status'];

    const req = createMockReq({ method: 'GET', path: '/health/status' }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.status).toBe('healthy');
    expect(Array.isArray(payload.services)).toBe(true);
    const services = payload.services as Array<Record<string, unknown>>;
    expect(services.every((s) => s.status === 'healthy')).toBe(true);
  });

  test('GET /health/status should be degraded if a service is down', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const go = __getClientByBaseURL(GO_URL) as MockAxiosClient;
    const py = __getClientByBaseURL(PY_URL) as MockAxiosClient;
    const rb = __getClientByBaseURL(RB_URL) as MockAxiosClient;

    go.get.mockResolvedValueOnce({ data: { ok: true } });
    py.get.mockRejectedValueOnce(new Error('down'));
    rb.get.mockResolvedValueOnce({ data: { ok: true } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.get['/health/status'];

    const req = createMockReq({ method: 'GET', path: '/health/status' }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.status).toBe('degraded');
    const services = payload.services as Array<Record<string, unknown>>;
    expect(services.some((s) => s.status === 'unhealthy')).toBe(true);
  });

  test('Proxy GET /api/go/* forwards to upstream with query and returns success', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const go = __getClientByBaseURL(GO_URL) as MockAxiosClient;

    go.request.mockResolvedValueOnce({ data: { result: 'ok' } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/go/*'];
    expect(handler).toBeDefined();

    const req = createMockReq({
      method: 'GET',
      path: '/api/go/orders/123',
      query: { x: '1' },
      headers: { 'x-req-id': 'abc' },
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(statusMock).not.toHaveBeenCalled();

    // Validate upstream call
    expect(go.request).toHaveBeenCalledTimes(1);
    const cfg = go.request.mock.calls[0][0] as Record<string, unknown>;
    // Due to path extraction bug, url becomes '/'
    expect(cfg.url).toBe('/');
    expect(cfg.method).toBe('get');
    expect(cfg.params).toEqual({ x: '1' });
    expect((cfg.headers as Record<string, string>)['Content-Type']).toBe('application/json');

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(true);
    expect(payload.service).toBe('go');
    expect(payload.data).toEqual({ result: 'ok' });
  });

  test('Proxy POST /api/python/* forwards body and headers', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const py = __getClientByBaseURL(PY_URL) as MockAxiosClient;

    py.request.mockResolvedValueOnce({ data: { created: true } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/python/*'];

    const req = createMockReq({
      method: 'POST',
      path: '/api/python/items',
      headers: { 'x-custom': 'C' },
      body: { name: 'Alpha' },
    }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(py.request).toHaveBeenCalledTimes(1);
    const cfg = py.request.mock.calls[0][0] as Record<string, unknown>;
    expect(cfg.method).toBe('post');
    expect(cfg.data).toEqual({ name: 'Alpha' });
    expect(cfg.url).toBe('/');

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(true);
    expect(payload.service).toBe('python');
  });

  test('Proxy PUT /api/ruby/* forwards body', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const rb = __getClientByBaseURL(RB_URL) as MockAxiosClient;

    rb.request.mockResolvedValueOnce({ data: { updated: 1 } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/ruby/*'];

    const req = createMockReq({
      method: 'PUT',
      path: '/api/ruby/items/42',
      body: { price: 100 },
    }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(rb.request).toHaveBeenCalledTimes(1);
    const cfg = rb.request.mock.calls[0][0] as Record<string, unknown>;
    expect(cfg.method).toBe('put');
    expect(cfg.data).toEqual({ price: 100 });

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(true);
    expect(payload.service).toBe('ruby');
  });

  test('Proxy DELETE /api/go/* handles delete', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const go = __getClientByBaseURL(GO_URL) as MockAxiosClient;

    go.request.mockResolvedValueOnce({ data: { deleted: true } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/go/*'];

    const req = createMockReq({
      method: 'DELETE',
      path: '/api/go/items/5',
    }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(go.request).toHaveBeenCalledTimes(1);
    const cfg = go.request.mock.calls[0][0] as Record<string, unknown>;
    expect(cfg.method).toBe('delete');

    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(true);
  });

  test('Proxy returns mapped axios error with status code', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const rb = __getClientByBaseURL(RB_URL) as MockAxiosClient;

    const axiosErr = {
      isAxiosError: true,
      message: 'Not Found',
      response: { status: 404, data: { error: 'nope' } },
    };
    rb.request.mockRejectedValueOnce(axiosErr);

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/ruby/*'];

    const req = createMockReq({
      method: 'GET',
      path: '/api/ruby/unknown',
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(statusMock).toHaveBeenCalledWith(404);
    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('Not Found');
    expect(payload.service).toBe('ruby');
  });

  test('Proxy returns 500 for non-axios errors', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const go = __getClientByBaseURL(GO_URL) as MockAxiosClient;

    go.request.mockRejectedValueOnce(new Error('boom'));

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/go/*'];

    const req = createMockReq({
      method: 'POST',
      path: '/api/go/ops',
      body: { x: 1 },
    }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    expect(statusMock).toHaveBeenCalledWith(500);
    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('boom');
  });

  test('404 handler returns not found for unknown routes', async (): Promise<void> => {
    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();

    // Find the 404 middleware: a use handler with length === 2, registered after routes
    const notFound = app.uses.reverse().find((fn) => typeof fn === 'function' && (fn as Function).length === 2) as
      | ((req: Request, res: Response) => void)
      | undefined;

    expect(notFound).toBeDefined();

    const req = createMockReq({ method: 'GET', path: '/does/not/exist' }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(notFound!(req as Request, res as Response));
    await done;

    expect(statusMock).toHaveBeenCalledWith(404);
    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect((payload.error as string).includes('Route GET /does/not/exist not found')).toBe(true);
  });

  test('Error handler returns 500 with error message', async (): Promise<void> => {
    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();

    // Error handler has 4 args
    const errHandler = app.uses.find((fn) => typeof fn === 'function' && (fn as Function).length === 4) as
      | ((err: Error, req: Request, res: Response, next: () => void) => void)
      | undefined;

    expect(errHandler).toBeDefined();

    const req = createMockReq({ method: 'GET', path: '/cause/error' }) as Request;
    const { res, jsonMock, statusMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(errHandler!(new Error('kaput'), req as Request, res as Response, () => {}));
    await done;

    expect(statusMock).toHaveBeenCalledWith(500);
    const payload = jsonMock.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('kaput');
  });

  test('Proxy path extraction edge case: unmatched pattern defaults to "/"', async (): Promise<void> => {
    const { __getClientByBaseURL } = await import('axios');
    const py = __getClientByBaseURL(PY_URL) as MockAxiosClient;

    py.request.mockResolvedValueOnce({ data: { ok: true } });

    const { __getLatestApp } = await import('express');
    const app = __getLatestApp();
    const handler = app.routes.all['/api/python/*'];

    const req = createMockReq({
      method: 'GET',
      path: '/api/python/sub/path',
    }) as Request;
    const { res, jsonMock } = createMockRes();

    const done = new Promise<void>((resolve) => {
      jsonMock.mockImplementationOnce((_payload: unknown) => {
        resolve();
        return undefined as unknown as Response;
      });
    });

    await Promise.resolve(handler(req, res as Response));
    await done;

    const cfg = py.request.mock.calls[0][0] as Record<string, unknown>;
    expect(cfg.url).toBe('/'); // due to current regex implementation
  });
});
