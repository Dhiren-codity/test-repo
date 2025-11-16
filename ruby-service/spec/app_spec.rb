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
    context 'when dependent services are healthy' do
      it 'returns healthy statuses for go and python services' do
        go_resp = double('response', code: 200)
        py_resp = double('response', code: 200)
        allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2).and_return(go_resp)
        allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                              timeout: 2).and_return(py_resp)

        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['ruby']['status']).to eq('healthy')
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a dependent service is unreachable' do
      it 'marks the service as unreachable' do
        allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health",
                                              timeout: 2).and_raise(StandardError.new('timeout'))
        py_resp = double('response', code: 200)
        allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                              timeout: 2).and_return(py_resp)

        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['go']['status']).to eq('unreachable')
        expect(json_response['services']['go']).to have_key('error')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a dependent service responds with non-200' do
      it 'marks the service as unhealthy' do
        go_resp = double('response', code: 500)
        py_resp = double('response', code: 200)
        allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health", timeout: 2).and_return(go_resp)
        allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                              timeout: 2).and_return(py_resp)

        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['go']['status']).to eq('unhealthy')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end
  end

  describe 'POST /analyze validations' do
    it 'returns 422 with validation errors when input is invalid' do
      error_double = double('ValidationError', to_hash: { field: 'content', message: 'is required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_double])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Validation failed')
      expect(json_response['details']).to include({ 'field' => 'content', 'message' => 'is required' })
    end

    it 'passes correlation id to downstream services and detects language from path' do
      correlation_id = 'abc-123'
      headers = { CorrelationIdMiddleware::CORRELATION_ID_HEADER => correlation_id, 'CONTENT_TYPE' => 'application/json' }
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input).and_wrap_original do |m, *args|
        m.call(*args)
      end

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'puts 1', path: 'file.rb'), correlation_id)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'puts 1', language: 'ruby'), correlation_id)
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'file.rb' }.to_json, headers
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq(correlation_id)
      expect(body['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review when params are provided' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'), nil)
        .and_return({ 'changes' => [] })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'), nil)
        .and_return({ 'score' => 75.0, 'issues' => [1] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq({ 'changes' => [] })
      expect(json_response['new_code_review']).to eq({ 'score' => 75.0, 'issues' => [1] })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns metrics, review and calculated overall_quality' do
      metrics = { 'complexity' => 1 }
      review = { 'score' => 90, 'issues' => [1] }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'x'), nil)
        .and_return(metrics)

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'x'), nil)
        .and_return(review)

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']).to eq(metrics)
      expect(json_response['review']).to eq(review)
      expect(json_response['overall_quality']).to eq(30.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and health score' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'print(1)' }]
      file_stats = { 'total_files' => 4, 'total_lines' => 100, 'languages' => { 'ruby' => 1, 'python' => 1 } }
      review_stats = { 'average_score' => 80.0, 'total_issues' => 2, 'average_complexity' => 0.5 }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files), nil)
        .and_return(file_stats)

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files), nil)
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('timestamp')
      expect(json_response['file_statistics']).to eq(file_stats)
      expect(json_response['review_statistics']).to eq(review_stats)
      expect(json_response['summary']['total_files']).to eq(4)
      expect(json_response['summary']['total_lines']).to eq(100)
      expect(json_response['summary']['languages']).to eq({ 'ruby' => 1, 'python' => 1 })
      expect(json_response['summary']['average_quality_score']).to eq(80.0)
      expect(json_response['summary']['total_issues']).to eq(2)
      expect(json_response['summary']['health_score']).to eq(64.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with total count' do
      traces = [
        { 'id' => 't1', 'path' => '/analyze' },
        { 'id' => 't2', 'path' => '/metrics' }
      ]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['total_traces']).to eq(2)
      expect(json_response['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('nope').and_return([])

      get '/traces/nope'
      expect(last_response.status).to eq(404)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for a correlation id' do
      traces = [{ 'path' => '/analyze' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('cid-1').and_return(traces)

      get '/traces/cid-1'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['correlation_id']).to eq('cid-1')
      expect(json_response['trace_count']).to eq(1)
      expect(json_response['traces']).to eq(traces)
    end
  end

  describe 'validation errors endpoints' do
    it 'returns collected validation errors' do
      errors = [{ 'field' => 'content', 'message' => 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['total_errors']).to eq(1)
      expect(json_response['errors']).to eq(errors)
    end

    it 'clears validation errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['message']).to eq('Validation errors cleared')
    end
  end
end
