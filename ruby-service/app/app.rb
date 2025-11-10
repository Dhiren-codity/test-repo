# frozen_string_literal: true

require 'sinatra/base'
require 'sinatra/json'
require 'rack/cors'
require 'httparty'
require 'json'
require_relative '../lib/correlation_id_middleware'
require_relative '../lib/request_validator'

class PolyglotAPI < Sinatra::Base
  use Rack::Cors do
    allow do
      origins '*'
      resource '*', headers: :any, methods: %i[get post put delete options]
    end
  end

  use CorrelationIdMiddleware

  configure do
    set :go_service_url, ENV['GO_SERVICE_URL'] || 'http://localhost:8080'
    set :python_service_url, ENV['PYTHON_SERVICE_URL'] || 'http://localhost:8081'
  end

  get '/health' do
    json status: 'healthy', service: 'ruby-api'
  end

  get '/status' do
    services_status = {
      ruby: { status: 'healthy' },
      go: check_service_health(settings.go_service_url),
      python: check_service_health(settings.python_service_url)
    }
    json services: services_status
  end

  post '/analyze' do
    begin
      body = request.body.read
      request.body.rewind
      request_data = body.empty? ? params : JSON.parse(body)
    rescue JSON::ParserError
      request_data = params
    end

    validation_errors = RequestValidator.validate_analyze_request(request_data)
    unless validation_errors.empty?
      return json({
        error: 'Validation failed',
        details: validation_errors.map(&:to_hash)
      }), 422
    end

    content = RequestValidator.sanitize_input(request_data['content'] || request_data[:content])
    path = RequestValidator.sanitize_input(request_data['path'] || request_data[:path]) || 'unknown'

    correlation_id = request.env[CorrelationIdMiddleware::CORRELATION_ID_HEADER]
    go_result = call_go_service('/parse', { content: content, path: path }, correlation_id)
    python_result = call_python_service('/review', { content: content, language: detect_language(path) }, correlation_id)

    json(
      file_info: go_result,
      review: python_result,
      summary: {
        language: go_result['language'],
        lines: go_result['lines']&.length || 0,
        review_score: python_result['score'],
        issues_count: python_result['issues']&.length || 0
      },
      correlation_id: correlation_id
    )
  end

  post '/diff' do
    begin
      body = request.body.read
      request.body.rewind
      request_data = body.empty? ? params : JSON.parse(body)
    rescue JSON::ParserError
      request_data = params
    end
    old_content = request_data['old_content'] || request_data[:old_content]
    new_content = request_data['new_content'] || request_data[:new_content]

    return json(error: 'Missing old_content or new_content'), 400 unless old_content && new_content

    diff_result = call_go_service('/diff', { old_content: old_content, new_content: new_content })
    new_review = call_python_service('/review', { content: new_content })

    json(
      diff: diff_result,
      new_code_review: new_review
    )
  end

  post '/metrics' do
    begin
      body = request.body.read
      request.body.rewind
      request_data = body.empty? ? params : JSON.parse(body)
    rescue JSON::ParserError
      request_data = params
    end
    content = request_data['content'] || request_data[:content]

    return json(error: 'Missing content'), 400 unless content

    metrics = call_go_service('/metrics', { content: content })
    review = call_python_service('/review', { content: content })

    json(
      metrics: metrics,
      review: review,
      overall_quality: calculate_quality_score(metrics, review)
    )
  end

  post '/dashboard' do
    begin
      body = request.body.read
      request.body.rewind
      request_data = body.empty? ? params : JSON.parse(body)
    rescue JSON::ParserError
      request_data = params
    end
    files = request_data['files'] || request_data[:files] || []

    return json(error: 'Missing files array'), 400 if files.empty?

    file_stats = call_go_service('/statistics', { files: files })
    review_stats = call_python_service('/statistics', { files: files })

    json(
      timestamp: Time.now.iso8601,
      file_statistics: file_stats,
      review_statistics: review_stats,
      summary: {
        total_files: file_stats['total_files'] || 0,
        total_lines: file_stats['total_lines'] || 0,
        languages: file_stats['languages'] || {},
        average_quality_score: review_stats['average_score'] || 0.0,
        total_issues: review_stats['total_issues'] || 0,
        health_score: calculate_dashboard_health_score(file_stats, review_stats)
      }
    )
  end

  get '/traces' do
    all_traces = CorrelationIdMiddleware.all_traces
    json(
      total_traces: all_traces.size,
      traces: all_traces
    )
  end

  get '/traces/:correlation_id' do
    correlation_id = params[:correlation_id]
    traces = CorrelationIdMiddleware.get_traces(correlation_id)

    if traces.empty?
      return json({ error: 'No traces found for correlation ID' }), 404
    end

    json(
      correlation_id: correlation_id,
      trace_count: traces.length,
      traces: traces
    )
  end

  get '/validation/errors' do
    errors = RequestValidator.get_validation_errors
    json(
      total_errors: errors.length,
      errors: errors
    )
  end

  delete '/validation/errors' do
    RequestValidator.clear_validation_errors
    json({ message: 'Validation errors cleared' })
  end

  private

  def check_service_health(url)
    response = HTTParty.get("#{url}/health", timeout: 2)
    { status: response.code == 200 ? 'healthy' : 'unhealthy' }
  rescue StandardError => e
    { status: 'unreachable', error: e.message }
  end

  def call_go_service(endpoint, data, correlation_id = nil)
    headers = { 'Content-Type' => 'application/json' }
    headers[CorrelationIdMiddleware::CORRELATION_ID_HEADER] = correlation_id if correlation_id

    response = HTTParty.post(
      "#{settings.go_service_url}#{endpoint}",
      body: data.to_json,
      headers: headers,
      timeout: 5
    )
    JSON.parse(response.body)
  rescue StandardError => e
    { error: e.message }
  end

  def call_python_service(endpoint, data, correlation_id = nil)
    headers = { 'Content-Type' => 'application/json' }
    headers[CorrelationIdMiddleware::CORRELATION_ID_HEADER] = correlation_id if correlation_id

    response = HTTParty.post(
      "#{settings.python_service_url}#{endpoint}",
      body: data.to_json,
      headers: headers,
      timeout: 5
    )
    JSON.parse(response.body)
  rescue StandardError => e
    { error: e.message }
  end

  def detect_language(path)
    ext = File.extname(path).downcase
    lang_map = {
      '.go' => 'go',
      '.py' => 'python',
      '.rb' => 'ruby',
      '.js' => 'javascript',
      '.ts' => 'typescript',
      '.java' => 'java'
    }
    lang_map[ext] || 'unknown'
  end

  def calculate_quality_score(metrics, review)
    return 0.0 unless metrics && review && !metrics['error'] && !review['error']

    complexity_penalty = (metrics['complexity'] || 0) * 0.1
    issue_penalty = (review['issues']&.length || 0) * 0.5
    review_score = review['score'] || 0

    base_score = review_score / 100.0
    final_score = base_score - complexity_penalty - issue_penalty

    score = (final_score * 100).round(2)
    score.clamp(0, 100)
  end

  def calculate_dashboard_health_score(file_stats, review_stats)
    return 0.0 unless file_stats && review_stats && !file_stats['error'] && !review_stats['error']

    avg_score = review_stats['average_score'] || 0
    total_issues = review_stats['total_issues'] || 0
    total_files = file_stats['total_files'] || 1
    avg_complexity = review_stats['average_complexity'] || 0

    issue_penalty = (total_issues.to_f / total_files) * 2
    complexity_penalty = avg_complexity * 30

    health_score = avg_score - issue_penalty - complexity_penalty
    [[health_score, 0].max, 100].min.round(2)
  end
end
