require 'securerandom'
require 'json'

class CorrelationIdMiddleware
  CORRELATION_ID_HEADER = 'X-Correlation-ID'.freeze
  TRACE_STORAGE = {}
  TRACE_MUTEX = Mutex.new

  def initialize(app)
    @app = app
  end

  def call(env)
    correlation_id = extract_or_generate_correlation_id(env)
    env[CORRELATION_ID_HEADER] = correlation_id

    request_start = Time.now
    trace_data = {
      service: 'ruby-api',
      method: env['REQUEST_METHOD'],
      path: env['PATH_INFO'],
      timestamp: request_start.iso8601,
      correlation_id: correlation_id
    }

    status, headers, response = @app.call(env)

    request_duration = ((Time.now - request_start) * 1000).round(2)
    trace_data[:duration_ms] = request_duration
    trace_data[:status] = status

    store_trace(correlation_id, trace_data)

    headers[CORRELATION_ID_HEADER] = correlation_id

    [status, headers, response]
  rescue StandardError => e
    trace_data[:error] = e.message
    trace_data[:status] = 500
    store_trace(correlation_id, trace_data)
    raise
  end

  private

  def extract_or_generate_correlation_id(env)
    existing_id = env['HTTP_X_CORRELATION_ID']
    return existing_id if existing_id && valid_correlation_id?(existing_id)

    generate_correlation_id
  end

  def generate_correlation_id
    "#{Time.now.to_i}-#{SecureRandom.hex(8)}"
  end

  def valid_correlation_id?(id)
    return false unless id.is_a?(String)
    return false if id.length > 100
    return false if id.length < 10
    id.match?(/^[\w\-]+$/)
  end

  def store_trace(correlation_id, trace_data)
    TRACE_MUTEX.synchronize do
      TRACE_STORAGE[correlation_id] ||= []
      TRACE_STORAGE[correlation_id] << trace_data
      cleanup_old_traces
    end
  end

  def cleanup_old_traces
    cutoff_time = Time.now - 3600
    TRACE_STORAGE.delete_if do |_id, traces|
      oldest_trace = traces.first
      oldest_trace && Time.parse(oldest_trace[:timestamp]) < cutoff_time
    end
  end

  def self.get_traces(correlation_id)
    TRACE_MUTEX.synchronize do
      TRACE_STORAGE[correlation_id] || []
    end
  end

  def self.all_traces
    TRACE_MUTEX.synchronize do
      TRACE_STORAGE.dup
    end
  end
end
