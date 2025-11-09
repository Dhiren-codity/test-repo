# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'time'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  Response = Struct.new(:code, :body)

  def app
    PolyglotAPI
  end

  def json_response
    JSON.parse(last_response.body)
  end

  # GET /status

  def test_status_returns_services_health
    HTTParty.stub :get, ->(url, _) { Response.new(200, nil) } do
      get '/status'
      assert_equal 200, last_response.status
      body = json_response
      assert_equal 'healthy', body['services']['ruby']['status']
      assert_equal 'healthy', body['services']['go']['status']
      assert_equal 'healthy', body['services']['python']['status']
    end
  end

  def test_status_handles_unreachable_service
    HTTParty.stub :get, lambda { |url, _|
      if url.include?('8081')
        raise StandardError, 'timeout'
      else
        Response.new(200, nil)
      end
    } do
      get '/status'
      assert_equal 200, last_response.status
      body = json_response
      assert_equal 'healthy', body['services']['go']['status']
      assert_equal 'unreachable', body['services']['python']['status']
      refute_nil body['services']['python']['error']
    end
  end

  # POST /diff

  def test_diff_success
    HTTParty.stub :post, lambda { |url, options|
      if url.include?('8080/diff')
        Response.new(nil, { diff: ['-old', '+new'] }.to_json)
      elsif url.include?('8081/review')
        Response.new(nil, { score: 88.5, issues: [] }.to_json)
      else
        flunk "Unexpected URL: #{url}"
      end
    } do
      post '/diff', { old_content: "a\nb", new_content: "a\nc" }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      body = json_response
      assert body['diff']
      assert body['new_code_review']
      assert_equal ['-old', '+new'], body['diff']['diff']
      assert_equal 88.5, body['new_code_review']['score']
    end
  end

  def test_diff_missing_params_returns_400
    post '/diff', { old_content: "only one side" }.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_match(/Missing old_content or new_content/, last_response.body)
  end

  # POST /metrics

  def test_metrics_success_and_quality_score_integration
    HTTParty.stub :post, lambda { |url, options|
      if url.include?('8080/metrics')
        Response.new(nil, { complexity: 1 }.to_json)
      elsif url.include?('8081/review')
        Response.new(nil, { score: 90, issues: ['x'] }.to_json)
      else
        flunk "Unexpected URL: #{url}"
      end
    } do
      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      body = json_response
      assert body['metrics']
      assert body['review']
      # quality score = 90/100 - (1*0.1) - (1*0.5) = 0.3 -> 30.0
      assert_in_delta 30.0, body['overall_quality'], 0.001
    end
  end

  def test_metrics_missing_content_returns_400
    post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_match(/Missing content/, last_response.body)
  end

  # POST /dashboard

  def test_dashboard_success_with_health_score
    HTTParty.stub :post, lambda { |url, options|
      if url.include?('8080/statistics')
        Response.new(nil, { total_files: 5, total_lines: 123, languages: { 'rb' => 3 } }.to_json)
      elsif url.include?('8081/statistics')
        Response.new(nil, { average_score: 90.0, total_issues: 10, average_complexity: 0.2 }.to_json)
      else
        flunk "Unexpected URL: #{url}"
      end
    } do
      files = [{ path: 'a.rb', content: 'a' }, { path: 'b.rb', content: 'b' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert_equal 200, last_response.status
      body = json_response

      # Timestamp is ISO8601
      assert_kind_of String, body['timestamp']
      assert Time.iso8601(body['timestamp'])

      summary = body['summary']
      assert_equal 5, summary['total_files']
      assert_equal 123, summary['total_lines']
      assert_equal({ 'rb' => 3 }, summary['languages'])
      assert_equal 90.0, summary['average_quality_score']
      assert_equal 10, summary['total_issues']
      # health score = 90 - ((10/5)*2) - (0.2*30) = 90 - 4 - 6 = 80
      assert_in_delta 80.0, summary['health_score'], 0.001
    end
  end

  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_match(/Missing files array/, last_response.body)
  end

  # Private utility methods

  def test_detect_language_mappings
    api = app.new!
    assert_equal 'python', api.send(:detect_language, 'test.py')
    assert_equal 'go', api.send(:detect_language, 'main.GO')
    assert_equal 'ruby', api.send(:detect_language, 'app.rb')
    assert_equal 'javascript', api.send(:detect_language, 'index.js')
    assert_equal 'typescript', api.send(:detect_language, 'types.d.ts')
    assert_equal 'java', api.send(:detect_language, 'Main.java')
    assert_equal 'unknown', api.send(:detect_language, 'Makefile')
  end

  def test_calculate_quality_score_normal_and_clamps
    api = app.new!

    # normal
    metrics = { 'complexity' => 2 }
    review = { 'score' => 80, 'issues' => ['a'] }
    # 0.8 - 0.2 - 0.5 = 0.1 -> 10.0
    assert_in_delta 10.0, api.send(:calculate_quality_score, metrics, review), 0.001

    # clamp high
    metrics2 = { 'complexity' => 0 }
    review2 = { 'score' => 120, 'issues' => [] }
    assert_equal 100.0, api.send(:calculate_quality_score, metrics2, review2)

    # error returns 0.0
    assert_equal 0.0, api.send(:calculate_quality_score, { 'error' => 'x' }, review2)
    assert_equal 0.0, api.send(:calculate_quality_score, metrics2, { 'error' => 'y' })
  end

  def test_calculate_dashboard_health_score_cases
    api = app.new!

    file_stats = { 'total_files' => 10 }
    review_stats = { 'average_score' => 75, 'total_issues' => 10, 'average_complexity' => 0.1 }
    # 75 - ((10/10)*2) - (0.1*30) = 75 - 2 - 3 = 70
    assert_in_delta 70.0, api.send(:calculate_dashboard_health_score, file_stats, review_stats), 0.001

    # negative -> clamp to 0
    low = api.send(:calculate_dashboard_health_score,
                   { 'total_files' => 1 }, { 'average_score' => 5, 'total_issues' => 100, 'average_complexity' => 1.0 })
    assert_equal 0.0, low

    # error -> 0.0
    assert_equal 0.0, api.send(:calculate_dashboard_health_score, { 'error' => 'x' }, review_stats)
    assert_equal 0.0, api.send(:calculate_dashboard_health_score, file_stats, { 'error' => 'y' })
  end

  def test_check_service_health_success_and_failure
    api = app.new!

    # success 200
    HTTParty.stub :get, ->(_url, _opts) { Response.new(200, nil) } do
      res = api.send(:check_service_health, 'http://service')
      assert_equal 'healthy', res[:status]
    end

    # non-200
    HTTParty.stub :get, ->(_url, _opts) { Response.new(500, nil) } do
      res = api.send(:check_service_health, 'http://service')
      assert_equal 'unhealthy', res[:status]
    end

    # exception -> unreachable
    HTTParty.stub :get, ->(_url, _opts) { raise StandardError, 'boom' } do
      res = api.send(:check_service_health, 'http://service')
      assert_equal 'unreachable', res[:status]
      assert_match(/boom/, res[:error])
    end
  end

  def test_call_go_and_python_service_success_and_error
    api = app.new!

    # success path
    HTTParty.stub :post, ->(_url, _opts) { Response.new(nil, { ok: true, v: 1 }.to_json) } do
      res1 = api.send(:call_go_service, '/parse', { a: 1 })
      res2 = api.send(:call_python_service, '/review', { b: 2 })
      assert_equal true, res1['ok']
      assert_equal 1, res2['v']
    end

    # error path
    HTTParty.stub :post, ->(_url, _opts) { raise StandardError, 'network error' } do
      res1 = api.send(:call_go_service, '/parse', { a: 1 })
      res2 = api.send(:call_python_service, '/review', { b: 2 })
      assert_match(/network error/, res1[:error])
      assert_match(/network error/, res2[:error])
    end
  end
end