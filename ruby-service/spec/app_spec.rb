# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'ostruct'
require 'time'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  def json_headers
    { 'CONTENT_TYPE' => 'application/json' }
  end

  # Endpoint: GET /status (exercises check_service_health)
  def test_status_reports_mixed_service_health
    ok_resp = OpenStruct.new(code: 200)
    bad_resp = OpenStruct.new(code: 500)

    HTTParty.stub(:get, ->(url, **_kwargs) { url.include?(':8080') ? ok_resp : bad_resp }) do
      get '/status'
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)
      assert_equal 'healthy', body['services']['go']['status']
      assert_equal 'unhealthy', body['services']['python']['status']
      assert_equal 'healthy', body['services']['ruby']['status']
    end
  end

  # Endpoint: POST /analyze missing content -> 400
  def test_analyze_missing_content_returns_400
    post '/analyze', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing content', body['error']
  end

  # Endpoint: POST /diff validations and success
  def test_diff_requires_both_contents
    post '/diff', { old_content: 'a' }.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing old_content or new_content', body['error']

    post '/diff', { new_content: 'b' }.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing old_content or new_content', body['error']
  end

  def test_diff_returns_combined_results
    HTTParty.stub(:post, lambda { |url, **_kwargs|
      if url.include?(':8080/diff')
        OpenStruct.new(body: { changes: 1, hunks: [] }.to_json)
      elsif url.include?(':8081/review')
        OpenStruct.new(body: { score: 90, issues: [] }.to_json)
      else
        raise "Unexpected URL: #{url}"
      end
    }) do
      post '/diff', { old_content: 'a', new_content: "b\n" }.to_json, json_headers
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)
      assert_equal 1, body['diff']['changes']
      assert_equal 90, body['new_code_review']['score']
    end
  end

  # Endpoint: POST /metrics and quality score calculation
  def test_metrics_returns_overall_quality
    HTTParty.stub(:post, lambda { |url, **_kwargs|
      if url.include?(':8080/metrics')
        OpenStruct.new(body: { complexity: 1.0 }.to_json)
      elsif url.include?(':8081/review')
        # review_score = 80, 1 issue
        OpenStruct.new(body: { score: 80, issues: ['x'] }.to_json)
      else
        raise "Unexpected URL: #{url}"
      end
    }) do
      post '/metrics', { content: 'def x(): pass' }.to_json, json_headers
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)
      # expected overall_quality = 80 - (1.0*10) - (1*50) = 20.0
      assert_in_delta 20.0, body['overall_quality'], 0.001
      assert_equal 1.0, body['metrics']['complexity']
      assert_equal 80, body['review']['score']
    end
  end

  def test_metrics_error_overall_quality_zero
    HTTParty.stub(:post, lambda { |url, **_kwargs|
      if url.include?(':8080/metrics')
        OpenStruct.new(body: { error: 'timeout' }.to_json)
      elsif url.include?(':8081/review')
        OpenStruct.new(body: { score: 95, issues: [] }.to_json)
      else
        raise "Unexpected URL: #{url}"
      end
    }) do
      post '/metrics', { content: 'puts 1' }.to_json, json_headers
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)
      assert_equal 0.0, body['overall_quality']
    end
  end

  # Endpoint: POST /dashboard validations and health score calculation
  def test_dashboard_requires_files
    post '/dashboard', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing files array', body['error']

    post '/dashboard', { files: [] }.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing files array', body['error']
  end

  def test_dashboard_returns_summary_with_health_score
    HTTParty.stub(:post, lambda { |url, **_kwargs|
      if url.include?(':8080/statistics')
        OpenStruct.new(body: {
          total_files: 2,
          total_lines: 120,
          languages: { 'ruby' => 1, 'python' => 1 }
        }.to_json)
      elsif url.include?(':8081/statistics')
        OpenStruct.new(body: {
          average_score: 90.0,
          total_issues: 3,
          average_complexity: 0.5
        }.to_json)
      else
        raise "Unexpected URL: #{url}"
      end
    }) do
      post '/dashboard', { files: [{ path: 'a.rb' }, { path: 'b.py' }] }.to_json, json_headers
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)
      assert body['timestamp']
      summary = body['summary']
      assert_equal 2, summary['total_files']
      assert_equal 120, summary['total_lines']
      assert_equal({ 'ruby' => 1, 'python' => 1 }, summary['languages'])
      # health_score = 90 - (3/2)*2 - (0.5*30) = 90 - 3 - 15 = 72.0
      assert_in_delta 72.0, summary['health_score'], 0.001
    end
  end

  # Unit: detect_language
  def test_detect_language_mappings
    inst = PolyglotAPI.new
    assert_equal 'python', inst.send(:detect_language, 'file.py')
    assert_equal 'go', inst.send(:detect_language, 'file.GO')
    assert_equal 'ruby', inst.send(:detect_language, '/tmp/a.rb')
    assert_equal 'javascript', inst.send(:detect_language, 'x.js')
    assert_equal 'typescript', inst.send(:detect_language, 'x.ts')
    assert_equal 'java', inst.send(:detect_language, 'x.java')
    assert_equal 'unknown', inst.send(:detect_language, 'x.unknown')
    assert_equal 'unknown', inst.send(:detect_language, 'no_extension')
  end

  # Unit: calculate_quality_score
  def test_calculate_quality_score_formulas_and_clamping
    inst = PolyglotAPI.new

    # Normal calculation: 80 - (2*10) - (1*50) = 80 - 20 - 50 = 10
    metrics = { 'complexity' => 2 }
    review = { 'score' => 80, 'issues' => ['a'] }
    assert_in_delta 10.0, inst.send(:calculate_quality_score, metrics, review), 0.001

    # Error present -> 0.0
    assert_equal 0.0, inst.send(:calculate_quality_score, { 'error' => 'x' }, review)
    assert_equal 0.0, inst.send(:calculate_quality_score, metrics, { 'error' => 'x' })

    # Clamp to 0
    metrics = { 'complexity' => 10 }
    review = { 'score' => 0, 'issues' => Array.new(3, 'i') }
    assert_equal 0, inst.send(:calculate_quality_score, metrics, review)

    # Clamp to 100
    metrics = { 'complexity' => 0 }
    review = { 'score' => 150, 'issues' => [] }
    assert_equal 100, inst.send(:calculate_quality_score, metrics, review)
  end

  # Unit: calculate_dashboard_health_score
  def test_calculate_dashboard_health_score
    inst = PolyglotAPI.new

    file_stats = { 'total_files' => 4 }
    review_stats = { 'average_score' => 88.0, 'total_issues' => 4, 'average_complexity' => 0.3 }
    # health = 88 - (4/4)*2 - (0.3*30) = 88 - 2 - 9 = 77
    assert_in_delta 77.0, inst.send(:calculate_dashboard_health_score, file_stats, review_stats), 0.001

    # Error -> 0.0
    assert_equal 0.0, inst.send(:calculate_dashboard_health_score, { 'error' => 'x' }, review_stats)
    assert_equal 0.0, inst.send(:calculate_dashboard_health_score, file_stats, { 'error' => 'x' })

    # Clamp to 0 and 100
    low = inst.send(:calculate_dashboard_health_score, { 'total_files' => 1 }, { 'average_score' => 5, 'total_issues' => 10, 'average_complexity' => 2 })
    high = inst.send(:calculate_dashboard_health_score, { 'total_files' => 10 }, { 'average_score' => 200, 'total_issues' => 0, 'average_complexity' => 0 })
    assert_equal 0.0, low
    assert_equal 100.0, high
  end

  # Unit: check_service_health
  def test_check_service_health_states
    inst = PolyglotAPI.new

    HTTParty.stub(:get, ->(_url, **_kwargs) { OpenStruct.new(code: 200) }) do
      result = inst.send(:check_service_health, 'http://example.com')
      assert_equal 'healthy', result[:status]
    end

    HTTParty.stub(:get, ->(_url, **_kwargs) { OpenStruct.new(code: 500) }) do
      result = inst.send(:check_service_health, 'http://example.com')
      assert_equal 'unhealthy', result[:status]
    end

    HTTParty.stub(:get, ->(_url, **_kwargs) { raise StandardError, 'boom' }) do
      result = inst.send(:check_service_health, 'http://example.com')
      assert_equal 'unreachable', result[:status]
      assert_match(/boom/, result[:error])
    end
  end
end