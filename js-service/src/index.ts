import crypto from 'crypto';
import express, { NextFunction, Request, Response } from 'express';
import cors from 'cors';
import axios from 'axios';

const app = express();

const allowedCorsOrigins = (process.env.CORS_ALLOWED_ORIGINS || 'http://localhost:3000,http://localhost:5173')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean);
const allowedCorsOriginSet = new Set(allowedCorsOrigins);
const CACHE_ADMIN_SECRET = process.env.CACHE_ADMIN_SECRET || '';

app.use(cors({
  origin: (origin, callback) => {
    if (!origin || allowedCorsOriginSet.has(origin)) {
      callback(null, true);
      return;
    }
    callback(new Error('Origin not allowed by CORS'));
  },
  allowedHeaders: ['Content-Type', 'X-Cache-Admin-Secret'],
  methods: ['GET', 'POST', 'OPTIONS']
}));
app.use(express.json());

interface CacheStats {
  service: string;
  hits: number;
  misses: number;
  size: number;
  hitRate: string;
}

interface CacheEntry {
  hits: number;
  misses: number;
  entries: Map<string, any>;
}

const serviceCache: Map<string, CacheEntry> = new Map();

const GO_SERVICE_URL = process.env.GO_SERVICE_URL || 'http://localhost:8080';
const PYTHON_SERVICE_URL = process.env.PYTHON_SERVICE_URL || 'http://localhost:8081';
const RUBY_SERVICE_URL = process.env.RUBY_SERVICE_URL || 'http://localhost:8082';

function secretsMatch(provided: string, expected: string): boolean {
  const providedBuffer = Buffer.from(provided);
  const expectedBuffer = Buffer.from(expected);

  return providedBuffer.length === expectedBuffer.length
    && crypto.timingSafeEqual(providedBuffer, expectedBuffer);
}

function requireCacheAdminSecret(req: Request, res: Response, next: NextFunction) {
  if (!CACHE_ADMIN_SECRET) {
    return res.status(503).json({ error: 'Cache admin secret not configured' });
  }

  const providedSecret = req.get('X-Cache-Admin-Secret') || '';
  if (!providedSecret || !secretsMatch(providedSecret, CACHE_ADMIN_SECRET)) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  next();
}

app.get('/health', (req: Request, res: Response) => {
  res.json({ status: 'healthy', service: 'js-cache' });
});

app.get('/cache/stats', (req: Request, res: Response) => {
  const stats: CacheStats[] = [];

  serviceCache.forEach((cache, serviceName) => {
    const total = cache.hits + cache.misses;
    const hitRate = total > 0 ? ((cache.hits / total) * 100).toFixed(2) : '0.00';

    stats.push({
      service: serviceName,
      hits: cache.hits,
      misses: cache.misses,
      size: cache.entries.size,
      hitRate: `${hitRate}%`
    });
  });

  res.json({
    timestamp: new Date().toISOString(),
    cacheStats: stats,
    totalServices: stats.length
  });
});

app.post('/cache/invalidate', requireCacheAdminSecret, (req: Request, res: Response) => {
  const { service, key } = req.body;

  if (!service) {
    return res.status(400).json({ error: 'Service name required' });
  }

  const cache = serviceCache.get(service);
  if (!cache) {
    return res.status(404).json({ error: `Cache for service '${service}' not found` });
  }

  if (key) {
    cache.entries.delete(key);
    res.json({
      message: `Cache key '${key}' invalidated for service '${service}'`,
      remainingEntries: cache.entries.size
    });
  } else {
    cache.entries.clear();
    cache.hits = 0;
    cache.misses = 0;
    res.json({
      message: `All cache cleared for service '${service}'`
    });
  }
});

app.post('/cache/invalidate-all', requireCacheAdminSecret, (req: Request, res: Response) => {
  serviceCache.clear();
  res.json({
    message: 'All caches cleared across all services',
    timestamp: new Date().toISOString()
  });
});

app.get('/cache/services', async (req: Request, res: Response) => {
  const services = [
    { name: 'go', url: GO_SERVICE_URL, port: 8080 },
    { name: 'python', url: PYTHON_SERVICE_URL, port: 8081 },
    { name: 'ruby', url: RUBY_SERVICE_URL, port: 8082 }
  ];

  const results = await Promise.all(
    services.map(async (service) => {
      try {
        const response = await axios.get(`${service.url}/health`, { timeout: 2000 });
        return {
          name: service.name,
          status: response.status === 200 ? 'online' : 'offline',
          port: service.port,
          cacheEnabled: serviceCache.has(service.name)
        };
      } catch (error) {
        return {
          name: service.name,
          status: 'offline',
          port: service.port,
          cacheEnabled: serviceCache.has(service.name)
        };
      }
    })
  );

  res.json({
    services: results,
    timestamp: new Date().toISOString()
  });
});

app.post('/cache/record', requireCacheAdminSecret, (req: Request, res: Response) => {
  const { service, key, hit } = req.body;

  if (!service) {
    return res.status(400).json({ error: 'Service name required' });
  }

  if (!serviceCache.has(service)) {
    serviceCache.set(service, {
      hits: 0,
      misses: 0,
      entries: new Map()
    });
  }

  const cache = serviceCache.get(service)!;

  if (hit) {
    cache.hits++;
  } else {
    cache.misses++;
    if (key) {
      cache.entries.set(key, { timestamp: Date.now() });
    }
  }

  res.json({ success: true });
});

const PORT = process.env.PORT || 8083;

app.listen(PORT, () => {
  console.log(`Cache Service starting on :${PORT}`);
});
