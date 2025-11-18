import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import request from 'supertest';

// Mock axios with controllable instances per create() call
vi.mock('axios', () => {
  const instances: any[] = [];
  const create = vi.fn((config: any) => {
    const inst = {
      request: vi.fn(),
      get: vi.fn(),
      defaults: { headers: {} },
      config,
    };
    instances.push(inst);
    return inst;
  });
  const isAxiosError = (err: any) => Boolean(err?.isAxiosError);
  return {
    default: { create, isAxiosError },
    create,
    isAxiosError,
    __instances: instances,
  };
});

async function loadApp() {
  vi.resetModules();

  // Silence console logs
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});

  // Prevent starting a real server
  const expressMod: any = await import('express');
  vi.spyOn(expressMod.default.application, 'listen').mockImplementation(() => ({ close: vi.fn() }));

  // Prevent adding real process signal listeners
  vi.spyOn(process, 'on').mockImplementation(() => process as any);

  // Clear axios instances created so far
  const axiosMod: any = await import('axios');
  axiosMod.__instances.length = 0;

  const mod = await import('../src/index');
  const app = mod.default;
  const instances = axiosMod.__instances as any[];

  return { app, axiosMod, instances };
}

describe('API Gateway Routes', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  test('GET / returns service info', async () => {
    const { app } = await loadApp();
    const res = await request(app).get('/').expect(200);

    expect(res.body).toHaveProperty('service', 'API Gateway');
    expect(res.body).toHaveProperty('endpoints');
    expect(res.body.endpoints).toHaveProperty('go');
    expect(res.body.endpoints).toHaveProperty('python');
    expect(res.body.endpoints).toHaveProperty('ruby');
  });

  test('GET /health/health returns healthy', async () => {
    const { app } = await loadApp();
    const res = await request(app).get('/health/health').expect(200);

    expect(res.body).toHaveProperty('status', 'healthy');
    expect(res.body).toHaveProperty('service', 'api-gateway');
    expect(res.body).toHaveProperty('timestamp');
  });

  test('GET /health/status returns degraded when one unhealthy', async () => {
    const { app, instances } = await loadApp();
    // 3 instances: go, python, ruby
    // Make go and python healthy, ruby unhealthy
    instances[0].get.mockResolvedValue({ status: 200, data: { ok: true } }); // go
    instances[1].get.mockResolvedValue({ status: 200, data: { ok: true } }); // python
    instances[2].get.mockRejectedValue(new Error('down')); // ruby

    const res = await request(app).get('/health/status').expect(200);
    expect(['healthy', 'degraded']).toContain(res.body.status);
    expect(res.body.status).toBe('degraded');

    expect(res.body).toHaveProperty('services');
    const svc = res.body.services.reduce((acc: any, s: any) => ({ ...acc, [s.service]: s.status }), {});
    expect(svc.go).toBeDefined();
    expect(svc.python).toBeDefined();
    expect(svc.ruby).toBeDefined();
    expect(Object.values(svc)).toContain('unhealthy');
  });

  test('Proxy GET /api/go/* success: forwards method and returns wrapped data', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockResolvedValue({ data: { hello: 'world' } });

    const res = await request(app)
      .get('/api/go/test/path?foo=bar')
      .set('x-custom', 'abc')
      .expect(200);

    expect(instances[0].request).toHaveBeenCalledTimes(1);
    const cfg = instances[0].request.mock.calls[0][0];
    expect(cfg.method).toBe('get');
    // As implemented, regex does not strip "/api/go", so url becomes "/"
    expect(cfg.url).toBe('/');
    expect(cfg.params).toMatchObject({ foo: 'bar' });
    expect(cfg.headers['x-custom']).toBe('abc');

    expect(res.body).toMatchObject({
      success: true,
      data: { hello: 'world' },
      service: 'go',
    });
  });

  test('Proxy POST /api/go/* success: forwards body', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockResolvedValue({ data: { ok: true } });

    const payload = { name: 'Alice' };
    const res = await request(app)
      .post('/api/go/items')
      .send(payload)
      .set('Content-Type', 'application/json')
      .expect(200);

    const cfg = instances[0].request.mock.calls[0][0];
    expect(cfg.method).toBe('post');
    expect(cfg.data).toEqual(payload);

    expect(res.body.success).toBe(true);
  });

  test('Proxy PUT /api/go/* success', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockResolvedValue({ data: { updated: 1 } });

    await request(app).put('/api/go/items/123').send({ name: 'Bob' }).expect(200);
    const cfg = instances[0].request.mock.calls[0][0];
    expect(cfg.method).toBe('put');
  });

  test('Proxy DELETE /api/go/* success', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockResolvedValue({ data: { deleted: 1 } });

    await request(app).delete('/api/go/items/123').expect(200);
    const cfg = instances[0].request.mock.calls[0][0];
    expect(cfg.method).toBe('delete');
  });

  test('Proxy to python and ruby map to correct clients', async () => {
    const { app, instances } = await loadApp();
    // go
    instances[0].request.mockResolvedValue({ data: { svc: 'go' } });
    // python
    instances[1].request.mockResolvedValue({ data: { svc: 'python' } });
    // ruby
    instances[2].request.mockResolvedValue({ data: { svc: 'ruby' } });

    await request(app).get('/api/python/echo').expect(200);
    await request(app).get('/api/ruby/echo').expect(200);

    expect(instances[1].request).toHaveBeenCalledTimes(1);
    expect(instances[2].request).toHaveBeenCalledTimes(1);
    expect(instances[0].request).toHaveBeenCalledTimes(0);
  });

  test('Proxy handles Axios error with response status', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { message: 'Not Found' } },
      message: 'Request failed with status code 404',
    });

    const res = await request(app).get('/api/go/missing').expect(404);
    expect(res.body.success).toBe(false);
    expect(res.body.error).toMatch(/404/);
  });

  test('Proxy handles non-Axios error as 500', async () => {
    const { app, instances } = await loadApp();
    instances[0].request.mockRejectedValue(new Error('boom'));

    const res = await request(app).get('/api/go/err').expect(500);
    expect(res.body.success).toBe(false);
    expect(res.body.error).toBe('boom');
  });

  test('404 handler returns JSON for unknown route', async () => {
    const { app } = await loadApp();

    const res = await request(app).get('/does-not-exist').expect(404);
    expect(res.body.success).toBe(false);
    expect(res.body.error).toContain('Route GET /does-not-exist not found');
    expect(res.body).toHaveProperty('timestamp');
  });

  test('Rate limiting returns 429 when exceeded', async () => {
    // Configure rate limit to 1 request
    process.env.RATE_LIMIT_MAX_REQUESTS = '1';
    const { app } = await loadApp();

    await request(app).get('/').expect(200);
    const res2 = await request(app).get('/').expect(429);
    expect(
      typeof res2.text === 'string'
        ? res2.text.includes('Too many requests')
        : res2.body?.message?.includes('Too many requests')
    ).toBeTruthy();
  });

  test('Error handling middleware returns 500 JSON', async () => {
    const { app } = await loadApp();

    // Extract the error-handling middleware (4-argument handler)
    const stack: any[] = (app as any)._router.stack;
    const errorLayer = stack.find((l) => l.handle && l.handle.length === 4);
    expect(errorLayer).toBeTruthy();

    // Mock req/res/next
    const req: any = { method: 'GET', path: '/x' };
    const jsonMock = vi.fn();
    const statusMock = vi.fn(() => ({ json: jsonMock }));
    const res: any = { status: statusMock, json: jsonMock };
    const next = vi.fn();

    // Call the error handler directly
    const err = new Error('Internal Boom');
    await (async () => errorLayer.handle(err, req, res, next))();

    expect(statusMock).toHaveBeenCalledWith(500);
    expect(jsonMock).toHaveBeenCalled();
    const payload = jsonMock.mock.calls[0][0];
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('Internal Boom');
  });
});
