require 'digest'
require 'json'

class CacheManager
  DEFAULT_MAX_HISTORY_SIZE = 1000

  def initialize(max_size = 1000, max_history_size = DEFAULT_MAX_HISTORY_SIZE)
    @cache = {}
    @access_times = {}
    @max_size = max_size
    @max_history_size = max_history_size
    @hit_count = 0
    @miss_count = 0
    @cache_history = []
  end

  def get(key)
    if @cache.key?(key)
      @access_times[key] = Time.now
      @hit_count += 1
      record_access(key, 'hit')
      return @cache[key]
    end

    @miss_count += 1
    record_access(key, 'miss')
    nil
  end

  def set(key, value, ttl = nil)
    if @cache.size >= @max_size
      evict_lru
    end

    @cache[key] = value
    @access_times[key] = Time.now

    record_access(key, 'set')
  end

  def compute(key, &block)
    cached = get(key)
    return cached if cached

    result = block.call
    set(key, result)
    result
  end

  def invalidate(key)
    @cache.delete(key)
    @access_times.delete(key)
  end

  def clear_all
    @cache.clear
    @access_times.clear
  end

  def stats
    {
      size: @cache.size,
      hits: @hit_count,
      misses: @miss_count,
      hit_rate: calculate_hit_rate,
      history_size: @cache_history.length
    }
  end

  def get_keys_by_pattern(pattern)
    @cache.keys.select { |k| k.to_s.match?(pattern) }
  end

  private

  def evict_lru
    oldest_key = @access_times.min_by { |k, v| v }&.first
    @cache.delete(oldest_key) if oldest_key
  end

  def record_access(key, action)
    @cache_history << {
      key: key,
      action: action,
      timestamp: Time.now,
      cache_size: @cache.size
    }

    trim_history
  end

  def calculate_hit_rate
    total = @hit_count + @miss_count
    total > 0 ? (@hit_count.to_f / total * 100).round(2) : 0.0
  end

  def trim_history
    excess_entries = @cache_history.length - @max_history_size
    @cache_history.shift(excess_entries) if excess_entries.positive?
  end
end
