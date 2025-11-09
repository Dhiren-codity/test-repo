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

  def json_response
    JSON.parse(last_response.body)
  end

  def test_status_endpoint_reports_service_health
    response_struct = Struct.new(:code)
    HTTParty.stub(:get, ->(url, **kwargs) {
      if url.include?('8080')
        response_struct.new(200)
      elsif url.include?('8081')
        raise StandardError, 'timeout'
      else
        response_struct.new(500)
      end
    }) do
      get '/status'
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = json_response

      assert_equal 'healthy', body.dig('services', 'ruby', 'status')
      assert_equal 'healthy', body.dig('services', 'go', 'status')
      assert_equal 'unreachable', body.dig('services', 'python', 'status')
      refute_nil body.dig('services', 'python', 'error')
    end
  end

  def test_analyze_missing_content_returns_400
    post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    body = json_response
    assert_equal 'Missing content', body['error']
  end

  def test_diff_success
    post_struct = Struct.new(:body)
    HTTParty.stub(:post, ->(url, **kwargs) {
      if url.include?(':8080') && url.end_with?('/diff')
        post_struct.new({ changed_lines: [1, 2, 3], summary: 'ok' }.to_json)
      elsif url.include?(':8081') && url.end_with?('/review')
        post_struct.new({ score: 88.2, issues: [{ id: 1 }] }.to_json)
      else
        post_struct.new({ error: 'unexpected' }.to_json)
      end
    }) do
      payload = { old_content: "a\nb\nc", new_content: "a\nb\nc\nd" }
      post '/diff', payload.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = json_response

      assert_equal [1, 2, 3], body.dig('diff', 'changed_lines')
      assert_in_delta 88.2, body.dig('new_code_review', 'score')
      assert_equal 1, body.dig('new_code_review', 'issues').length
    end
  end

  def test_diff_missing_params_returns_400
    post '/diff', { old_content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing old_content or new_content', json_response['error']
  end

  def test_metrics_success_and_quality_score_calculation
    post_struct = Struct.new(:body)
    HTTParty.stub(:post, ->(url, **kwargs) {
      if url.include?(':8080') && url.end_with?('/metrics')
        post_struct.new({ complexity: 1 }.to_json)
      elsif url.include?(':8081') && url.end_with?('/review')
        post_struct.new({ score: 90, issues: [{}] }.to_json)
      else
        post_struct.new({ error: 'unexpected' }.to_json)
      end
    }) do
      post '/metrics', { content: 'print("hi")' }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = json_response

      # Expected: base 0.9 -> 90 - complexity_penalty(0.1*100=10) - issue_penalty(0.5*100=50) = 30.0
      assert_in_delta 30.0, body['overall_quality'], 0.001
      assert_equal 1, body.dig('metrics', 'complexity')
      assert_equal 90, body.dig('review', 'score')
      assert_equal 1, body.dig('review', 'issues').length
    end
  end

  def test_metrics_missing_content_returns_400
    post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing content', json_response['error']
  end

  def test_dashboard_success_with_health_score_calculation
    post_struct = Struct.new(:body)
    file_stats = {
      total_files: 5,
      total_lines: 1000,
      languages: { 'ruby' => 3, 'python' => 2 }
    }
    review_stats = {
      average_score: 85.0,
      total_issues: 10,
      average_complexity: 0.5
    }
    HTTParty.stub(:post, ->(url, **kwargs) {
      if url.include?(':8080') && url.end_with?('/statistics')
        post_struct.new(file_stats.to_json)
      elsif url.include?(':8081') && url.end_with?('/statistics')
        post_struct.new(review_stats.to_json)
      else
        post_struct.new({ error: 'unexpected' }.to_json)
      end
    }) do
      files = [
        { path: 'a.rb', content: 'puts :a' },
        { path: 'b.py', content: 'print(1)' }
      ]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?, "Expected 200, got #{last_response.status}"
      body = json_response

      # Health score: 85 - (10/5*2 = 4) - (0.5*30 = 15) = 66.0
      assert_equal 5, body.dig('summary', 'total_files')
      assert_equal 1000, body.dig('summary', 'total_lines')
      assert_equal({ 'ruby' => 3, 'python' => 2 }, body.dig('summary', 'languages'))
      assert_in_delta 85.0, body.dig('summary', 'average_quality_score')
      assert_equal 10, body.dig('summary', 'total_issues')
      assert_in_delta 66.0, body.dig('summary', 'health_score'), 0.001
      refute_nil body['timestamp']
      assert_match(/\d{4}-\d{2}-\d{2}T/, body['timestamp'])
    end
  end

  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    assert_equal 'Missing files array', json_response['error']
  end

  def test_detect_language_mappings
    instance = PolyglotAPI.new
    assert_equal 'go', instance.send(:detect_language, 'main.go')
    assert_equal 'python', instance.send(:detect_language, 'script.py')
    assert_equal 'ruby', instance.send(:detect_language, 'app.rb')
    assert_equal 'javascript', instance.send(:detect_language, 'app.js')
    assert_equal 'typescript', instance.send(:detect_language, 'app.ts')
    assert_equal 'java', instance.send(:detect_language, 'Main.java')
    assert_equal 'unknown', instance.send(:detect_language, 'README.md')
  end

  def test_calculate_quality_score_returns_zero_on_errors
    instance = PolyglotAPI.new
    assert_equal 0.0, instance.send(:calculate_quality_score, { 'error' => 'x' }, { 'score' => 90 })
    assert_equal 0.0, instance.send(:calculate_quality_score, { 'complexity' => 1 }, { 'error' => 'y' })
    assert_equal 0.0, instance.send(:calculate_quality_score, nil, { 'score' => 90 })
    assert_equal 0.0, instance.send(:calculate_quality_score, { 'complexity' => 1 }, nil)
  end

  def test_calculate_quality_score_computation_and_clamping
    instance = PolyglotAPI.new
    # Normal case
    metrics = { 'complexity' => 2 }
    review = { 'score' => 92, 'issues' => [{}, {}] } # penalties: 0.2 + 1.0; base 0.92 => 72.0
    assert_in_delta 72.0, instance.send(:calculate_quality_score, metrics, review), 0.001

    # Clamp low
    metrics2 = { 'complexity' => 50 }
    review2 = { 'score' => 10, 'issues' => Array.new(30, {}) }
    assert_equal 0, instance.send(:calculate_quality_score, metrics2, review2)

    # Clamp high
    metrics3 = { 'complexity' => 0 }
    review3 = { 'score' => 100, 'issues' => [] }
    assert_equal 100, instance.send(:calculate_quality_score, metrics3, review3)
  end

  def test_calculate_dashboard_health_score_with_errors_and_bounds
    instance = PolyglotAPI.new
    file_stats = { 'total_files' => 5 }
    review_stats_error = { 'error' => 'x' }
    assert_equal 0.0, instance.send(:calculate_dashboard_health_score, file_stats, review_stats_error)

    # Clamp low
    low = instance.send(:calculate_dashboard_health_score,
                        { 'total_files' => 1 },
                        { 'average_score' => 10, 'total_issues' => 100, 'average_complexity' => 5 })
    assert_equal 0.0, low

    # Clamp high
    high = instance.send(:calculate_dashboard_health_score,
                         { 'total_files' => 1 },
                         { 'average_score' => 200, 'total_issues' => 0, 'average_complexity' => 0 })
    assert_equal 100.0, high
  end
end