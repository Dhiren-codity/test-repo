# WARNING: This test file may contain syntax errors
# Generated after 3 attempts with validation errors
# Last error: ruby: /tmp/tmp061ki8w1.rb:70: syntax error, unexpected ')', expecting `end' or dummy end (SyntaxError)
...t_any_instance_of(PolyglotAPI)).not_to receive(:call_go_serv...
...                              ^
# Please review and fix any issues before running

# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/app'
require 'time'

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

  describe 'POST /analyze (additional cases)' do
    it 'detects language based on file extension and passes to python service' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'def test(): pass', path: 'code/test.py'), kind_of(String))
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'def test(): pass', language: 'python'), kind_of(String))
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'code/test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']['review_score']).to eq(90.0)
    end

    it 'falls back to params when JSON parsing fails' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 70.0, 'issues' => [] })

      post '/analyze', content: 'puts 1', path: 'test.rb'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']['language']).to eq('ruby')
    end

    it 'returns 422 when validation fails' do
      error_obj = double('ValidationError', to_hash: { field: 'content', message: 'is required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])
      allow(RequestValidator).to receive(:sanitize_input).and_wrap_original do |m, *args|
        args.first
      end
      expect_any_instance_of(PolyglotAPI)).not_to receive(:call_go_service)
      expect_any_instance_of(PolyglotAPI)).not_to receive(:call_python_service)

      post '/analyze', { path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to be_an(Array)
      expect(body['details'].first['field']).to eq('content')
    end
  end

  describe 'GET /status' do
    it 'returns health status for downstream services' do
      allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health", timeout: 2)
        .and_return(double(code: 500))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['ruby']['status']).to eq('healthy')
      expect(body['services']['go']['status']).to eq('healthy')
      expect(body['services']['python']['status']).to eq('unhealthy')
    end

    it 'marks a service as unreachable when request raises error' do
      allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2)
        .and_raise(StandardError.new('timeout'))
      allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health", timeout: 2)
        .and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['go']['status']).to eq('unreachable')
      expect(body['services']['python']['status']).to eq('healthy')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new review when valid payload is provided' do
      diff = { 'changes' => 2, 'diff' => '@@ -1 +1 @@' }
      review = { 'score' => 88.5, 'issues' => [] }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return(diff)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).with('/review', hash_including(content: 'b'))
        .and_return(review)

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq(diff)
      expect(body['new_code_review']).to eq(review)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end

    it 'returns metrics, review and overall_quality (clamped to 0)' do
      metrics = { 'complexity' => 3 }
      review = { 'score' => 80, 'issues' => ['a', 'b'] }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).with('/metrics', hash_including(content: 'code'))
        .and_return(metrics)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).with('/review', hash_including(content: 'code'))
        .and_return(review)

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to eq(metrics)
      expect(body['review']).to eq(review)
      expect(body['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end

    it 'returns dashboard data with computed health score and timestamp' do
      fixed_time = Time.parse('2023-01-01T00:00:00Z')
      allow(Time).to receive(:now).and_return(fixed_time)

      file_stats = { 'total_files' => 10, 'total_lines' => 1000, 'languages' => { 'rb' => 5 } }
      review_stats = { 'average_score' => 90.0, 'total_issues' => 5, 'average_complexity' => 0.5 }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).with('/statistics', hash_including(files: array_including(hash_including(:path))))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).with('/statistics', hash_including(files: array_including(hash_including(:path))))
        .and_return(review_stats)

      files = [{ path: 'a.rb', content: 'puts 1' }, { path: 'b.rb', content: 'puts 2' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['timestamp']).to eq(fixed_time.iso8601)
      expect(body['file_statistics']).to eq(file_stats)
      expect(body['review_statistics']).to eq(review_stats)
      expect(body['summary']['total_files']).to eq(10)
      expect(body['summary']['total_lines']).to eq(1000)
      expect(body['summary']['languages']).to eq({ 'rb' => 5 })
      expect(body['summary']['average_quality_score']).to eq(90.0)
      expect(body['summary']['total_issues']).to eq(5)
      expect(body['summary']['health_score']).to eq(74.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [{ 'id' => '1' }, { 'id' => '2' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns traces for a specific correlation id' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([{ 'step' => 'start' }])

      get '/traces/abc'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('abc')
      expect(body['trace_count']).to eq(1)
      expect(body['traces']).to be_an(Array)
    end

    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('missing').and_return([])

      get '/traces/missing'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end
  end

  describe 'Validation errors endpoints' do
    it 'GET /validation/errors returns stored errors' do
      errors = [{ 'code' => 'E1', 'message' => 'Invalid' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors']).to eq(errors)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
