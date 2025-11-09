require 'sinatra/base'
begin
  require 'sinatra/json'
rescue LoadError
  # optional: we'll provide our own json helper
end
begin
  require 'rack/cors'
rescue LoadError
  # optional CORS support
end
begin
  require 'httparty'
rescue LoadError
  module HTTParty
    Response = Struct.new(:code, :body)
    def self.get(*)
      Response.new(503, { error: 'httparty not installed' }.to_json)
    end
    def self.post(*)
      Response.new(503, { error: 'httparty not installed' }.to_json)
    end
  end
end
require 'json'
require 'time'

class PolyglotAPI < Sinatra::Base
  if defined?(Rack::Cors)
    use Rack::Cors do
      allow do
        origins '*'
        resource '*', headers: :any, methods: %i[get post put delete options]
      end
    end
  end

  configure do
    set :go_service_url, ENV['GO_SERVICE_URL'] || 'http://localhost:8080'
    set :python_service_url, ENV['PYTHON_SERVICE_URL'] || 'http://localhost:8081'
  end

  helpers do
    def json(payload)
      content_type :json
      JSON.generate(payload)
    end
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
    request_data = parse_request_data

    content = request_data['content'] || request_data[:content]
    path = request_data['path'] || request_data[:path] || 'unknown'

    halt 400, json(error: 'Missing content') unless content

    go_result = call_go_service('/parse', { content: content, path: path })
    python_result = call_python_service('/review', { content: content, language: detect_language(path) })

    json(
      file_info: go_result,
      review: python_result,
      summary: {
        language: go_result['language'],
        lines: go_result['lines']&.length || 0,
        review_score: python_result['score'],
        issues_count: python_result['issues']&.length || 0
      }
    )
  end

  post '/diff' do
    request_data = parse_request_data

    old_content = request_data['old_content'] || request_data[:old_content]
    new_content = request_data['new_content'] || request_data[:new_content]

    halt 400, json(error: 'Missing old_content or new_content') unless old_content && new_content

    diff_result = call_go_service('/diff', { old_content: old_content, new_content: new_content })
    new_review = call_python_service('/review', { content: new_content })

    json(
      diff: diff_result,
      new_code_review: new_review
    )
  end

  post '/metrics' do
    request_data = parse_request_data
    content = request_data['content'] || request_data[:content]

    halt 400, json(error: 'Missing content') unless content

    metrics = call_go_service('/metrics', { content: content })
    review = call_python_service('/review', { content: content })

    json(
      metrics: metrics,
      review: review,
      overall_quality: calculate_quality_score(metrics, review)
    )
  end

  post '/dashboard' do
    request_data = parse_request_data
    files = request_data['files'] || request_data[:files] || []

    halt 400, json(error: 'Missing files array') if files.empty?

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

  private

  def parse_request_data
    body = request.body.read.to_s
    request.body.rewind
    if body.strip.empty?
      params
    else
      JSON.parse(body)
    end
  rescue JSON::ParserError
    params
  end

  def check_service_health(url)
    response = HTTParty.get("#{url}/health", timeout: 2)
    { status: response.code == 200 ? 'healthy' : 'unhealthy' }
  rescue StandardError => e
    { status: 'unreachable', error: e.message }
  end

  def call_go_service(endpoint, data)
    response = HTTParty.post(
      "#{settings.go_service_url}#{endpoint}",
      body: data.to_json,
      headers: { 'Content-Type' => 'application/json' },
      timeout: 5
    )
    JSON.parse(response.body)
  rescue StandardError => e
    { error: e.message }
  end

  def call_python_service(endpoint, data)
    response = HTTParty.post(
      "#{settings.python_service_url}#{endpoint}",
      body: data.to_json,
      headers: { 'Content-Type' => 'application/json' },
      timeout: 5
    )
    JSON.parse(response.body)
  rescue StandardError => e
    { error: e.message }
  end

  def detect_language(path)
    ext = File.extname(path.to_s).downcase
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