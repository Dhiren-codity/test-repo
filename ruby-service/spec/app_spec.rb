# test/services/polyglot_api_service_test.rb
# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'time'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  def parse_json
    JSON.parse(last_response.body)
  end

  def fake_get_response(code)
    Struct.new(:code).new(code)
  end

  def fake_post_response(body_hash)
    Struct.new(:body).new(body_hash.to_json)
  end

  # GET /status

  def test_status_returns_health_for_all_services_when_healthy
    HTTParty.stub(:get, ->(_url, **_opts) { fake_get_response(200) }) do
      get '/status'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 'healthy', json['services']['ruby']['status']
      assert_equal 'healthy', json['services']['go']['status']
      assert_equal 'healthy', json['services']['python']['status']
    end
  end

  def test_status_handles_unhealthy_and_unreachable_services
    HTTParty.stub(:get, lambda { |url, **_opts|
      if url.include?(':8080') # go service
        raise StandardError, 'timeout'
      else # python service
        fake_get_response(503)
      end
    }) do
      get '/status'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 'unreachable', json['services']['go']['status']
      assert_equal 'unhealthy', json['services']['python']['status']
    end
  end

  # POST /diff

  def test_diff_success_returns_diff_and_new_code_review
    HTTParty.stub(:post, lambda { |url, body:, headers:, timeout:|
      if url.include?(':8080/diff')
        fake_post_response({ diff: '--- a\n+++ b\n' })
      elsif url.include?(':8081/review')
        fake_post_response({ score: 90.0, issues: [] })
      else
        flunk "Unexpected POST URL: #{url}"
      end
    }) do
      payload = { old_content: 'a = 1', new_content: 'a = 2' }.to_json
      post '/diff', payload, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      json = parse_json
      assert json.key?('diff')
      assert json.key?('new_code_review')
      assert_equal 90.0, json['new_code_review']['score']
    end
  end

  def test_diff_missing_content_returns_400
    post '/diff', { old_content: 'only old' }.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    json = parse_json
    assert_equal 'Missing old_content or new_content', json['error']
  end

  # POST /metrics

  def test_metrics_success_computes_overall_quality
    HTTParty.stub(:post, lambda { |url, body:, headers:, timeout:|
      if url.include?(':8080/metrics')
        fake_post_response({ complexity: 1 })
      elsif url.include?(':8081/review')
        fake_post_response({ score: 90.0, issues: [] })
      else
        flunk "Unexpected POST URL: #{url}"
      end
    }) do
      post '/metrics', { content: 'def x(): pass' }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      json = parse_json
      # expected: base 0.9 - complexity 0.1 - issues 0 = 0.8 -> 80.0
      assert_in_delta 80.0, json['overall_quality'], 0.001
      assert json.key?('metrics')
      assert json.key?('review')
    end
  end

  def test_metrics_returns_400_when_missing_content
    post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    json = parse_json
    assert_equal 'Missing content', json['error']
  end

  def test_metrics_overall_quality_zero_when_service_errors
    HTTParty.stub(:post, lambda { |url, body:, headers:, timeout:|
      if url.include?(':8080/metrics')
        # Simulate error path inside call_go_service (exception -> {error: message})
        raise StandardError, 'network error'
      elsif url.include?(':8081/review')
        fake_post_response({ score: 75.0, issues: %w[a b] })
      else
        flunk "Unexpected POST URL: #{url}"
      end
    }) do
      post '/metrics', { content: 'something' }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 0.0, json['overall_quality']
    end
  end

  # POST /dashboard

  def test_dashboard_success_calculates_summary_and_health_score
    file_stats = {
      'total_files' => 5,
      'total_lines' => 100,
      'languages' => { 'ruby' => 2, 'python' => 3 }
    }
    review_stats = {
      'average_score' => 85.0,
      'total_issues' => 4,
      'average_complexity' => 1.2
    }
    fixed_time = Time.utc(2024, 1, 1, 12, 0, 0)

    HTTParty.stub(:post, lambda { |url, body:, headers:, timeout:|
      if url.include?(':8080/statistics')
        fake_post_response(file_stats)
      elsif url.include?(':8081/statistics')
        fake_post_response(review_stats)
      else
        flunk "Unexpected POST URL: #{url}"
      end
    }) do
      Time.stub(:now, fixed_time) do
        post '/dashboard', { files: [{ path: 'a.rb', content: 'x' }] }.to_json, 'CONTENT_TYPE' => 'application/json'
      end
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal fixed_time.iso8601, json['timestamp']
      assert_equal 5, json['summary']['total_files']
      assert_equal 100, json['summary']['total_lines']
      assert_equal({ 'ruby' => 2, 'python' => 3 }, json['summary']['languages'])
      assert_in_delta 85.0, json['summary']['average_quality_score'], 0.001
      assert_equal 4, json['summary']['total_issues']
      # health_score = 85 - (4/5*2) - (1.2*30) = 47.4
      assert_in_delta 47.4, json['summary']['health_score'], 0.001
    end
  end

  def test_dashboard_returns_400_when_missing_files
    post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    json = parse_json
    assert_equal 'Missing files array', json['error']
  end

  # Private helper methods (unit-level)

  def test_detect_language_mappings
    instance = app.new
    assert_equal 'ruby', instance.send(:detect_language, 'foo.rb')
    assert_equal 'python', instance.send(:detect_language, 'bar.PY')
    assert_equal 'go', instance.send(:detect_language, '/path/main.go')
    assert_equal 'unknown', instance.send(:detect_language, 'README.md')
  end

  def test_check_service_health_success_and_exception
    instance = app.new

    # success path
    HTTParty.stub(:get, ->(_url, **_opts) { fake_get_response(200) }) do
      result = instance.send(:check_service_health, 'http://service')
      assert_equal 'healthy', result[:status]
    end

    # exception path
    HTTParty.stub(:get, ->(_url, **_opts) { raise StandardError, 'boom' }) do
      result = instance.send(:check_service_health, 'http://service')
      assert_equal 'unreachable', result[:status]
      assert_match(/boom/, result[:error])
    end
  end

  def test_calculate_quality_score_boundaries
    instance = app.new

    # Upper clamp to 100
    metrics = { 'complexity' => 0 }
    review = { 'score' => 100, 'issues' => [] }
    assert_in_delta 100.0, instance.send(:calculate_quality_score, metrics, review), 0.001

    # Lower clamp to 0
    metrics = { 'complexity' => 10 }
    review = { 'score' => 10, 'issues' => %w[a b c d e] }
    assert_in_delta 0.0, instance.send(:calculate_quality_score, metrics, review), 0.001

    # Error short-circuit
    metrics = { 'error' => 'oops' }
    review = { 'score' => 80, 'issues' => [] }
    assert_in_delta 0.0, instance.send(:calculate_quality_score, metrics, review), 0.001
  end

  def test_calculate_dashboard_health_score_boundaries
    instance = app.new

    # Upper clamp to 100
    fs = { 'total_files' => 1 }
    rs = { 'average_score' => 150, 'total_issues' => 0, 'average_complexity' => 0 }
    assert_in_delta 100.0, instance.send(:calculate_dashboard_health_score, fs, rs), 0.001

    # Lower clamp to 0
    fs = { 'total_files' => 10 }
    rs = { 'average_score' => 10, 'total_issues' => 100, 'average_complexity' => 5 }
    assert_in_delta 0.0, instance.send(:calculate_dashboard_health_score, fs, rs), 0.001

    # Error short-circuit
    fs = { 'error' => 'bad' }
    rs = { 'average_score' => 90, 'total_issues' => 0, 'average_complexity' => 0 }
    assert_in_delta 0.0, instance.send(:calculate_dashboard_health_score, fs, rs), 0.001
  end
end