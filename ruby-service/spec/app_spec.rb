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

  def parse_json
    JSON.parse(last_response.body)
  end

  def test_status_all_services_healthy
    response_double = OpenStruct.new(code: 200, body: '{"status":"healthy"}')

    HTTParty.stub(:get, proc { |_url, **_kwargs| response_double }) do
      get '/status'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 'healthy', json.dig('services', 'ruby', 'status')
      assert_equal 'healthy', json.dig('services', 'go', 'status')
      assert_equal 'healthy', json.dig('services', 'python', 'status')
    end
  end

  def test_status_handles_unreachable_and_unhealthy
    HTTParty.stub(:get, proc { |url, **_kwargs|
      if url.include?('8080') # go
        raise Errno::ECONNREFUSED, 'connection refused'
      else # python
        OpenStruct.new(code: 500, body: '')
      end
    }) do
      get '/status'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 'unreachable', json.dig('services', 'go', 'status')
      assert_equal 'unhealthy', json.dig('services', 'python', 'status')
    end
  end

  def test_diff_success
    HTTParty.stub(:post, proc { |url, **kwargs|
      if url.include?('8080/diff')
        OpenStruct.new(body: { changes: [{ line: 1, type: 'add' }], summary: '1 addition' }.to_json)
      elsif url.include?('8081/review')
        OpenStruct.new(body: { score: 88, issues: [{ id: 1, message: 'ok' }] }.to_json)
      else
        flunk("Unexpected POST URL: #{url} with #{kwargs.inspect}")
      end
    }) do
      payload = { old_content: 'a = 1', new_content: 'a = 2' }.to_json
      post '/diff', payload, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal '1 addition', json.dig('diff', 'summary')
      assert_equal 88, json.dig('new_code_review', 'score')
    end
  end

  def test_diff_missing_params_returns_400
    post '/diff', { new_content: 'only new' }.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing old_content or new_content', parse_json['error']
  end

  def test_metrics_success_with_invalid_json_fallback
    HTTParty.stub(:post, proc { |url, **_kwargs|
      if url.include?('8080/metrics')
        OpenStruct.new(body: { complexity: 3, lines: 10 }.to_json)
      elsif url.include?('8081/review')
        OpenStruct.new(body: { score: 92, issues: [] }.to_json)
      else
        flunk("Unexpected POST URL: #{url}")
      end
    }) do
      # Send invalid JSON body but provide params via query string so parser falls back to params
      post '/metrics?content=puts+123', 'invalid { json', 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      json = parse_json
      assert_equal 3, json.dig('metrics', 'complexity')
      assert_equal 92, json.dig('review', 'score')
      # overall_quality should be computed and within 0..100
      assert json['overall_quality'].is_a?(Numeric)
      assert_operator json['overall_quality'], :>=, 0
      assert_operator json['overall_quality'], :<=, 100
    end
  end

  def test_metrics_missing_content_returns_400
    post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing content', parse_json['error']
  end

  def test_dashboard_success_and_summary_calculation
    fixed_time = Time.utc(2023, 1, 1, 12, 0, 0)

    files = [
      { 'path' => 'a.rb', 'content' => 'puts 1' },
      { 'path' => 'b.py', 'content' => 'print(1)' }
    ]

    HTTParty.stub(:post, proc { |url, **_kwargs|
      if url.include?('8080/statistics')
        OpenStruct.new(body: {
          total_files: 2,
          total_lines: 2,
          languages: { 'ruby' => 1, 'python' => 1 }
        }.to_json)
      elsif url.include?('8081/statistics')
        OpenStruct.new(body: {
          average_score: 85.5,
          total_issues: 3,
          average_complexity: 0.2
        }.to_json)
      else
        flunk("Unexpected POST URL: #{url}")
      end
    }) do
      Time.stub :now, fixed_time do
        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        assert_equal 200, last_response.status
        json = parse_json
        assert_equal fixed_time.iso8601, json['timestamp']
        assert_equal 2, json.dig('summary', 'total_files')
        assert_equal 2, json.dig('summary', 'total_lines')
        assert_equal 85.5, json.dig('summary', 'average_quality_score')
        assert_equal 3, json.dig('summary', 'total_issues')
        # Health score should be computed and within 0..100
        assert json.dig('summary', 'health_score').is_a?(Numeric)
        assert_operator json.dig('summary', 'health_score'), :>=, 0
        assert_operator json.dig('summary', 'health_score'), :<=, 100
      end
    end
  end

  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing files array', parse_json['error']
  end

  def test_detect_language_mappings_and_unknown
    svc = PolyglotAPI.new
    assert_equal 'python', svc.send(:detect_language, 'foo/bar/test.py')
    assert_equal 'ruby', svc.send(:detect_language, 'test.rb')
    assert_equal 'go', svc.send(:detect_language, 'main.go')
    assert_equal 'javascript', svc.send(:detect_language, 'app.js')
    assert_equal 'typescript', svc.send(:detect_language, 'app.ts')
    assert_equal 'java', svc.send(:detect_language, 'App.java')
    assert_equal 'unknown', svc.send(:detect_language, 'README')
  end

  def test_calculate_quality_score_valid_and_clamped
    svc = PolyglotAPI.new

    metrics = { 'complexity' => 2 }
    review = { 'score' => 80, 'issues' => ['one'] }
    # base 0.8 - complexity 0.2 - issues 0.5 = 0.1 => 10.0
    assert_equal 10.0, svc.send(:calculate_quality_score, metrics, review)

    # Forces clamp to 0
    metrics2 = { 'complexity' => 5 }
    review2 = { 'score' => 60, 'issues' => %w[a b c] } # 0.6 - 0.5 - 1.5 = -1.4 => 0 after clamp
    assert_equal 0, svc.send(:calculate_quality_score, metrics2, review2)

    # Returns 0.0 if errors present
    assert_equal 0.0, svc.send(:calculate_quality_score, { 'error' => 'x' }, review)
    assert_equal 0.0, svc.send(:calculate_quality_score, metrics, { 'error' => 'y' })
    assert_equal 0.0, svc.send(:calculate_quality_score, nil, review)
    assert_equal 0.0, svc.send(:calculate_quality_score, metrics, nil)
  end

  def test_calculate_dashboard_health_score_valid_and_error_cases
    svc = PolyglotAPI.new

    file_stats = { 'total_files' => 10 }
    review_stats = { 'average_score' => 90, 'total_issues' => 10, 'average_complexity' => 0.5 }
    # issue_penalty = (10/10)*2 = 2; complexity_penalty = 0.5*30 = 15; health = 90-2-15 = 73.0
    assert_equal 73.0, svc.send(:calculate_dashboard_health_score, file_stats, review_stats)

    # Clamp within [0, 100]
    review_stats2 = { 'average_score' => 5, 'total_issues' => 50, 'average_complexity' => 2.0 }
    score = svc.send(:calculate_dashboard_health_score, file_stats, review_stats2)
    assert_operator score, :>=, 0
    assert_operator score, :<=, 100

    # Error returns 0.0
    assert_equal 0.0, svc.send(:calculate_dashboard_health_score, { 'error' => 'x' }, review_stats)
    assert_equal 0.0, svc.send(:calculate_dashboard_health_score, file_stats, { 'error' => 'y' })
  end

  def test_check_service_health_states
    svc = PolyglotAPI.new

    # Healthy
    HTTParty.stub(:get, proc { |_url, **_kwargs| OpenStruct.new(code: 200, body: '') }) do
      res = svc.send(:check_service_health, 'http://example.com')
      assert_equal 'healthy', res[:status]
    end

    # Unhealthy (non-200)
    HTTParty.stub(:get, proc { |_url, **_kwargs| OpenStruct.new(code: 503, body: '') }) do
      res = svc.send(:check_service_health, 'http://example.com')
      assert_equal 'unhealthy', res[:status]
    end

    # Unreachable (exception)
    HTTParty.stub(:get, proc { |_url, **_kwargs| raise Timeout::Error, 'timeout' }) do
      res = svc.send(:check_service_health, 'http://example.com')
      assert_equal 'unreachable', res[:status]
      assert_match(/timeout/i, res[:error])
    end
  end
end