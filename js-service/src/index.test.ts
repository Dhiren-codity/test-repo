import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from 'vitest';
import type { SuperTest, Test } from 'supertest';
import supertest from 'supertest';

vi.mock('axios', () => {
  const handlers: Record<'go' | 'python' | 'ruby', ((req: any) => any | Promise<any>) | null> = {
    go: null,
    python: null,
    ruby: null,
  };
  const health: Record<'go' | 'python' | 'ruby', boolean> = {
    go: true,
    python: true,
    ruby: true,
  };

  const resolveService = (baseURL: string | undefined) => {
    const url = baseURL || '';
    if (url.includes('go')) return 'go';
    if (url.includes('python')) return 'python';
    return 'ruby';
  };

  const create = (config: any = {}) => {
    const svc = resolveService(config.baseURL);
    const client = {
      defaults: { headers: { 'Content-Type': 'application/json' } },
      request: vi.fn(async (reqConfig: any) => {
        const handler = handlers[svc as 'go' | 'python' | 'ruby'];
        if (handler) {
          const result = await handler(reqConfig);
          return { data: result };
        }
        return {
          data: {
            echo: {
              service: svc,
              method: String(reqConfig.method || '').toUpperCase(),
              url: reqConfig.url,
              data: reqConfig.data,
              params: reqConfig.params,
              headers: reqConfig.headers,
            },
          },
        };
      }),
      get: vi.fn(async (url: string) => {
        if (url === '/health') {
          if (health[svc as 'go' | 'python' | 'ruby']) {
            return { data: { status: 'ok' } };
          }
          const err: any = new Error('unhealthy');
          err.isAxiosError = true;
          err.response = { status: 503, data: { error: 'unhealthy' } };
          throw err;
        }
        return { data: {} };
      }),
    };
    return client;
  };

  const isAxiosError = (e: any) => !!e?.isAxiosError;

  const controller = {
    __setHealth: (service: 'go' | 'python' | 'ruby', value: boolean) => {
      health[service] = value;
    },
    __setRequestHandler: (
      service: 'go' | 'python' | 'ruby',
      handler: ((req: any) => any | Promise<any>) | null
    ) => {
      handlers[service] = handler;
    },
    __reset: () => {
      handlers.go = null;
      handlers.python = null;
      handlers.ruby = null;
      health.go = true;
      health.python = true;
      health.ruby = true;
    },
  };

  const axiosLike: any = { create, isAxiosError, ...controller };
  return { default: axiosLike };
});

describe('API Gateway Routes', () => {
  let app: any;
  let request: SuperTest<Test>;
  const axiosMock: any = vi.mocked(await import('axios')).default;

  beforeAll(async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    process.env.PORT = '0';
    const mod = await import('../src/index');
    app = mod.default;
    request = supertest(app);
  });

  beforeEach(() => {
    axiosMock.__reset();
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('GET / should respond with service metadata', async () => {
    const res = await request.get('/');
    expect(res.status).toBe(200);
    expect(res.body?.service).toBe('API Gateway');
    expect(res.body?.endpoints?.go).toBe('/api/go/*');
    expect(res.body?.endpoints?.python).toBe('/api/python/*');
    expect(res.body?.endpoints?.ruby).toBe('/api/ruby/*');
  });

  it('GET /health/health should return healthy status', async () => {
    const res = await request.get('/health/health');
    expect(res.status).toBe(200);
    expect(res.body?.status).toBe('healthy');
    expect(res.body?.service).toBe('api-gateway');
    expect(typeof res.body?.timestamp).toBe('string');
  });

  it('GET /health/status should report all services healthy', async () => {
    axiosMock.__setHealth('go', true);
    axiosMock.__setHealth('python', true);
    axiosMock.__setHealth('ruby', true);

    const res = await request.get('/health/status');
    expect(res.status).toBe(200);
    expect(res.body?.status).toBe('healthy');
    expect(res.body?.services).toBeInstanceOf(Array);
    expect(res.body?.services.every((s: any) => s.status === 'healthy')).toBe(true);
  });

  it('GET /health/status should report degraded when any service unhealthy', async () => {
    axiosMock.__setHealth('go', true);
    axiosMock.__setHealth('python', false);
    axiosMock.__setHealth('ruby', true);

    const res = await request.get('/health/status');
    expect(res.status).toBe(200);
    expect(res.body?.status).toBe('degraded');
    const python = res.body?.services.find((s: any) => s.service === 'python');
    expect(python?.status).toBe('unhealthy');
  });

  it('GET /api/go/foo should proxy and include query params', async () => {
    axiosMock.__setRequestHandler('go', vi.fn(async (req: any) => {
      return { from: 'go', method: req.method, url: req.url, params: req.params };
    }));
    const res = await request.get('/api/go/foo?x=1&y=2');
    expect(res.status).toBe(200);
    expect(res.body?.success).toBe(true);
    expect(res.body?.service).toBe('go');
    expect(res.body?.data).toEqual({ from: 'go', method: 'get', url: '/foo', params: { x: '1', y: '2' } });
  });

  it('POST /api/python/bar should proxy and include request body', async () => {
    axiosMock.__setRequestHandler('python', vi.fn(async (req: any) => {
      return { from: 'python', method: req.method, data: req.data };
    }));
    const payload = { hello: 'world', n: 42 };
    const res = await request.post('/api/python/bar').send(payload);

    expect(res.status).toBe(200);
    expect(res.body?.success).toBe(true);
    expect(res.body?.service).toBe('python');
    expect(res.body?.data).toEqual({ from: 'python', method: 'post', data: payload });
  });

  it('PUT /api/ruby/baz should proxy and include headers', async () => {
    axiosMock.__setRequestHandler('ruby', vi.fn(async (req: any) => {
      return {
        from: 'ruby',
        method: req.method,
        header: req.headers['x-custom-header'],
        url: req.url,
      };
    }));
    const res = await request
      .put('/api/ruby/baz?q=ok')
      .set('X-Custom-Header', 'my-value')
      .send({ a: 1 });

    expect(res.status).toBe(200);
    expect(res.body?.success).toBe(true);
    expect(res.body?.service).toBe('ruby');
    expect(res.body?.data).toEqual({
      from: 'ruby',
      method: 'put',
      header: 'my-value',
      url: '/baz',
    });
  });

  it('DELETE /api/go/qux should proxy delete method', async () => {
    axiosMock.__setRequestHandler('go', vi.fn(async (req: any) => {
      return { from: 'go', method: req.method, url: req.url };
    }));
    const res = await request.delete('/api/go/qux');

    expect(res.status).toBe(200);
    expect(res.body?.success).toBe(true);
    expect(res.body?.service).toBe('go');
    expect(res.body?.data).toEqual({ from: 'go', method: 'delete', url: '/qux' });
  });

  it('Proxy should map upstream AxiosError to response status and error body', async () => {
    axiosMock.__setRequestHandler('python', vi.fn(async () => {
      const err: any = new Error('Upstream fail');
      err.isAxiosError = true;
      err.response = { status: 502, data: { code: 'BAD_GATEWAY' } };
      throw err;
    }));

    const res = await request.get('/api/python/fails');

    expect(res.status).toBe(502);
    expect(res.body?.success).toBe(false);
    expect(res.body?.error).toContain('Upstream fail');
    expect(res.body?.service).toBe('python');
  });

  it('Unknown routes should return 404 JSON', async () => {
    const res = await request.get('/not-found-route');
    expect(res.status).toBe(404);
    expect(res.body?.success).toBe(false);
    expect(String(res.body?.error)).toMatch(/Route GET \/not-found-route not found/);
  });

  it('Proxy root path should map to "/" when wildcard matches only base', async () => {
    axiosMock.__setRequestHandler('go', vi.fn(async (req: any) => {
      return { method: req.method, url: req.url || '/' };
    }));
    // Express route '/api/go/*' with trailing slash should still hit wildcard and produce targetPath '/'
    const res = await request.get('/api/go/');
    expect(res.status).toBe(200);
    expect(res.body?.success).toBe(true);
    expect(res.body?.data?.url).toBe('/');
  });

  it('Does not require authentication for public endpoints', async () => {
    const res = await request.get('/');
    expect(res.status).toBe(200);
  });
});

describe('Rate limiting behavior', () => {
  let appLimited: any;
  let requestLimited: SuperTest<Test>;

  beforeAll(async () => {
    vi.restoreAllMocks();
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.resetModules();
    process.env.PORT = '0';
    process.env.RATE_LIMIT_MAX_REQUESTS = '1';
    const mod = await import('../src/index');
    appLimited = mod.default;
    requestLimited = supertest(appLimited);
  });

  it('should return 429 after exceeding rate limit', async () => {
    const first = await requestLimited.get('/health/health');
    expect(first.status).toBe(200);

    const second = await requestLimited.get('/health/health');
    expect(second.status).toBe(429);
    expect(String(second.text)).toMatch(/Too many requests/i);
  });
});
