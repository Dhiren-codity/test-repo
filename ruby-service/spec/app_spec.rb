# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    it 'returns status for all services when healthy' do
      go_resp = double(code: 200)
      py_resp = double(code: 200)
      allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2).and_return(go_resp)
      allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health", timeout: 2).and_return(py_resp)

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['ruby']['status']).to eq('healthy')
      expect(body['services']['go']['status']).to eq('healthy')
      expect(body['services']['python']['status']).to eq('healthy')
    end

    it 'marks services as unhealthy or unreachable appropriately' do
      go_resp = double(code: 500)
      allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2).and_return(go_resp)
      allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                            timeout: 2).and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['go']['status']).to eq('unhealthy')
      expect(body['services']['python']['status']).to eq('unreachable')
      expect(body['services']['python']).to have_key('error')
    end
  end

  describe 'POST /analyze additional cases' do
    it 'returns 422 when validation fails with invalid JSON body' do
      errors = [double(to_hash: { field: 'content', message: 'is required' })]
      allow(RequestValidator).to receive(:validate_analyze_request).and_return(errors)

      post '/analyze', '{ invalid json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to be_an(Array)
      expect(body['details'].first['field']).to eq('content')
    end

    it 'forwards and returns the correlation id and detects language from path' do
      correlation_id = 'corr-123'
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) do |arg|
        arg
      end

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'def a; end', path: 'test.rb'), correlation_id)
        .and_return({ 'language' => 'ruby', 'lines' => ['def a; end'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'def a; end', language: 'ruby'), correlation_id)
        .and_return({ 'score' => 95, 'issues' => [] })

      header CorrelationIdMiddleware::CORRELATION_ID_HEADER, correlation_id
      post '/analyze', { content: 'def a; end', path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq(correlation_id)
      expect(body['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new review on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: "a\n", new_content: "b\n"), nil)
        .and_return({ 'diff' => '@@ -1 +1 @@' })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: "b\n"), nil)
        .and_return({ 'score' => 80, 'issues' => ['naming'] })

      post '/diff', { old_content: "a\n", new_content: "b\n" }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq({ 'diff' => '@@ -1 +1 @@' })
      expect(body['new_code_review']['score']).to eq(80)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and computed overall_quality' do
      metrics = { 'complexity' => 1 }
      review = { 'issues' => ['minor'], 'score' => 90 }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'), nil)
        .and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'), nil)
        .and_return(review)

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to eq(metrics)
      expect(body['review']).to eq(review)
      expect(body['overall_quality']).to eq(30.0)
    end

    it 'returns overall_quality 0.0 when downstream services error' do
      allow(HTTParty).to receive(:post).and_raise(StandardError.new('timeout'))

      post '/metrics', { content: 'anything' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to have_key('error')
      expect(body['review']).to have_key('error')
      expect(body['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and health score' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.rb', 'content' => 'puts 2' }]
      file_stats = { 'total_files' => 2, 'total_lines' => 4, 'languages' => { 'ruby' => 2 } }
      review_stats = { 'average_score' => 88.0, 'total_issues' => 2, 'average_complexity' => 0.5 }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files), nil)
        .and_return(file_stats)

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files), nil)
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['file_statistics']).to eq(file_stats)
      expect(body['review_statistics']).to eq(review_stats)
      expected_health = (88.0 - ((2.0 / 2) * 2) - (0.5 * 30)).round(2)
      expected_health = [[expected_health, 0].max, 100].min
      expect(body['summary']['health_score']).to eq(expected_health)
      expect(body['summary']['total_files']).to eq(2)
      expect(body['summary']['languages']).to eq({ 'ruby' => 2 })
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with total count' do
      traces = [{ 'id' => 't1', 'events' => [] }, { 'id' => 't2', 'events' => [] }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces exist for id' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('missing').and_return([])

      get '/traces/missing'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for a given correlation id' do
      traces = [{ 'step' => 'start' }, { 'step' => 'end' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return(traces)

      get '/traces/abc'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('abc')
      expect(body['trace_count']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'validation errors endpoints' do
    it 'returns current validation errors' do
      errors = [{ 'field' => 'content', 'message' => 'is required' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors']).to eq(errors)
    end

    it 'clears validation errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
