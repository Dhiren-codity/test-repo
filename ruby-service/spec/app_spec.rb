# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'time'

# Adjust the path based on repository structure
require_relative '../../ruby-service/app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  def json_headers
    { 'CONTENT_TYPE' => 'application/json' }
  end

  # NEW: GET /status - aggregates health statuses; handles healthy and unreachable services
  def test_status_aggregates_health_and_unreachable
    stub = lambda do |url, timeout:|
      if url.include?('8080') # go service
        Struct.new(:code).new(200)
      else # python service
        raise StandardError, 'connection refused'
      end
    end

    HTTParty.stub(:get, stub) do
      get '/status'
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)

      assert_equal 'healthy', body['services']['go']['status']
      assert_equal 'unreachable', body['services']['python']['status']
      assert_match(/connection refused/, body['services']['python']['error'])
      assert_equal 'healthy', body['services']['ruby']['status']
    end
  end

  # NEW: POST /analyze - missing content error
  def test_analyze_missing_content_returns_400
    post '/analyze', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing content', body['error']
  end

  # NEW: POST /diff - missing params error
  def test_diff_missing_params_returns_400
    post '/diff', { old_content: 'a' }.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing old_content or new_content', body['error']
  end

  # NEW: POST /diff - success; combines diff and new review
  def test_diff_success_combines_diff_and_review
    stub = lambda do |url, body:, headers:, timeout:|
      data = JSON.parse(body)
      if url.include?('8080') && url.end_with?('/diff')
        Struct.new(:body).new({ changes: [{ line: 1, type: 'add' }], summary: '1 addition' }.to_json)
      elsif url.include?('8081') && url.end_with?('/review')
        Struct.new(:body).new({ score: 92.5, issues: [] }.to_json)
      else
        raise "Unexpected POST URL: #{url}"
      end
    end

    HTTParty.stub(:post, stub) do
      payload = { old_content: "a\n", new_content: "a\nb\n" }
      post '/diff', payload.to_json, json_headers

      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)
      assert body.key?('diff'), 'Expected diff key'
      assert body.key?('new_code_review'), 'Expected new_code_review key'
      assert_equal '1 addition', body['diff']['summary']
      assert_equal 92.5, body['new_code_review']['score']
    end
  end

  # NEW: POST /metrics - success; computes overall_quality from metrics and review
  def test_metrics_success_overall_quality_positive
    stub = lambda do |url, body:, headers:, timeout:|
      if url.include?('8080') && url.end_with?('/metrics')
        Struct.new(:body).new({ complexity: 0 }.to_json)
      elsif url.include?('8081') && url.end_with?('/review')
        Struct.new(:body).new({ score: 88, issues: [] }.to_json)
      else
        raise "Unexpected POST URL: #{url}"
      end
    end

    HTTParty.stub(:post, stub) do
      post '/metrics', { content: 'puts :ok' }.to_json, json_headers
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)
      assert_equal 88.0, body['overall_quality']
      assert_equal 88, body['review']['score']
      assert_equal 0, (body['metrics']['complexity'] || 0)
    end
  end

  # NEW: POST /metrics - failure when a downstream service errors; overall_quality should be 0.0
  def test_metrics_service_error_leads_to_overall_quality_zero
    stub = lambda do |url, body:, headers:, timeout:|
      if url.include?('8080') && url.end_with?('/metrics')
        raise StandardError, 'metrics timeout'
      elsif url.include?('8081') && url.end_with?('/review')
        Struct.new(:body).new({ score: 75, issues: [1] }.to_json)
      else
        raise "Unexpected POST URL: #{url}"
      end
    end

    HTTParty.stub(:post, stub) do
      post '/metrics', { content: 'code' }.to_json, json_headers
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)
      assert_equal 0.0, body['overall_quality']
      assert body['metrics'].key?('error'), 'Expected metrics error captured'
    end
  end

  # NEW: POST /dashboard - missing files array error
  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing files array', body['error']
  end

  # NEW: POST /dashboard - success; verifies summary and health score calculation
  def test_dashboard_success_includes_summary_and_health_score
    stub = lambda do |url, body:, headers:, timeout:|
      if url.include?('8080') && url.end_with?('/statistics')
        Struct.new(:body).new({
          total_files: 2,
          total_lines: 100,
          languages: { 'ruby' => 2 }
        }.to_json)
      elsif url.include?('8081') && url.end_with?('/statistics')
        Struct.new(:body).new({
          average_score: 80.0,
          total_issues: 2,
          average_complexity: 0.1
        }.to_json)
      else
        raise "Unexpected POST URL: #{url}"
      end
    end

    HTTParty.stub(:post, stub) do
      files = [
        { path: 'a.rb', content: 'puts 1' },
        { path: 'b.rb', content: 'puts 2' }
      ]
      post '/dashboard', { files: files }.to_json, json_headers
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)

      assert body.key?('timestamp')
      assert body.key?('file_statistics')
      assert body.key?('review_statistics')
      assert body.key?('summary')

      summary = body['summary']
      assert_equal 2, summary['total_files']
      assert_equal 100, summary['total_lines']
      assert_equal 80.0, summary['average_quality_score']
      # health_score = 80 - (2/2)*2 - (0.1*30) = 75.0
      assert_in_delta 75.0, summary['health_score'], 0.001
    end
  end

  # NEW: Private method - detect_language mapping
  def test_detect_language_mapping
    inst = PolyglotAPI.new!
    assert_equal 'ruby', inst.send(:detect_language, 'foo.rb')
    assert_equal 'python', inst.send(:detect_language, 'bar.PY')
    assert_equal 'go', inst.send(:detect_language, 'main.go')
    assert_equal 'javascript', inst.send(:detect_language, 'app.js')
    assert_equal 'typescript', inst.send(:detect_language, 'app.ts')
    assert_equal 'java', inst.send(:detect_language, 'Main.java')
    assert_equal 'unknown', inst.send(:detect_language, 'Makefile')
  end

  # NEW: Private method - calculate_quality_score clamps and penalizes
  def test_calculate_quality_score_bounds_and_penalties
    inst = PolyglotAPI.new!

    # Clamps to 100 when base score > 100 and no penalties
    metrics = { 'complexity' => 0 }
    review = { 'score' => 150, 'issues' => [] }
    assert_equal 100, inst.send(:calculate_quality_score, metrics, review)

    # Clamps to 0 when penalties push negative
    metrics2 = { 'complexity' => 5 } # penalty 0.5
    review2 = { 'score' => 0, 'issues' => [1, 2, 3] } # penalty 1.5
    assert_equal 0, inst.send(:calculate_quality_score, metrics2, review2)
  end

  # NEW: Ensures detect_language is used to pass language to python service within /analyze
  def test_analyze_uses_detected_language_for_python_service
    go_resp = ->(_url, body:, headers:, timeout:) do
      # Always return file_info from go parse
      Struct.new(:body).new({ language: 'ruby', lines: ['puts 1'] }.to_json)
    end
    py_resp = ->(url, body:, headers:, timeout:) do
      data = JSON.parse(body)
      # Ensure language detected from path is passed to python reviewer
      raise "Expected ruby language, got #{data['language']}" unless data['language'] == 'ruby'
      Struct.new(:body).new({ score: 90, issues: [] }.to_json)
    end

    stub = lambda do |url, body:, headers:, timeout:|
      if url.include?('8080') && url.end_with?('/parse')
        go_resp.call(url, body: body, headers: headers, timeout: timeout)
      elsif url.include?('8081') && url.end_with?('/review')
        py_resp.call(url, body: body, headers: headers, timeout: timeout)
      else
        raise "Unexpected POST URL: #{url}"
      end
    end

    HTTParty.stub(:post, stub) do
      post '/analyze', { content: 'puts 1', path: 'foo.rb' }.to_json, json_headers
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = JSON.parse(last_response.body)
      assert_equal 'ruby', body['summary']['language']
      assert_equal 90, body['summary']['review_score']
    end
  end
end