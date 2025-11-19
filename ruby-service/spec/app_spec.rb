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
    context 'when all services are healthy' do
      it 'returns healthy statuses' do
        allow(HTTParty).to receive(:get).and_return(double(code: 200))
        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['ruby']['status']).to eq('healthy')
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when one service is unreachable' do
      it 'marks it as unreachable with error message' do
        allow(HTTParty).to receive(:get) do |url, _opts|
          raise StandardError, 'boom' if url == "#{PolyglotAPI.settings.python_service_url}/health"

          double(code: 200)
        end
        get '/status'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['services']['go']['status']).to eq('healthy')
        expect(json['services']['python']['status']).to eq('unreachable')
        expect(json['services']['python']['error']).to eq('boom')
      end
    end

    context 'when a service responds but unhealthy' do
      it 'marks it as unhealthy' do
        allow(HTTParty).to receive(:get) do |url, _opts|
          if url == "#{PolyglotAPI.settings.go_service_url}/health"
            double(code: 500)
          else
            double(code: 200)
          end
        end
        get '/status'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['services']['go']['status']).to eq('unhealthy')
        expect(json['services']['python']['status']).to eq('healthy')
      end
    end
  end

  describe 'POST /analyze (additional scenarios)' do
    context 'when validation fails' do
      it 'returns 422 with details' do
        error_obj = double(to_hash: { field: 'content', message: 'required' })
        allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])

        post '/analyze', { content: '' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(422)
        json = JSON.parse(last_response.body)
        expect(json['error']).to eq('Validation failed')
        expect(json['details']).to include({ 'field' => 'content', 'message' => 'required' })
      end
    end

    context 'propagates correlation id and detects language' do
      it 'passes correlation id header and language to downstream services' do
        allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
        allow(RequestValidator).to receive(:sanitize_input) { |v| v }

        expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/parse', hash_including(content: 'puts 1', path: 'foo.rb'), 'cid-123')
          .and_return({ 'language' => 'ruby', 'lines' => %w[a b] })

        expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'puts 1', language: 'ruby'), 'cid-123')
          .and_return({ 'score' => 90, 'issues' => [] })

        header CorrelationIdMiddleware::CORRELATION_ID_HEADER, 'cid-123'
        post '/analyze', { content: 'puts 1', path: 'foo.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['correlation_id']).to eq('cid-123')
        expect(json['summary']['language']).to eq('ruby')
      end
    end

    context 'with invalid JSON falls back to params' do
      it 'uses query params when body is invalid JSON' do
        allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
        allow(RequestValidator).to receive(:sanitize_input) { |v| v }

        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'language' => 'python', 'lines' => %w[1 2] })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({ 'score' => 75, 'issues' => [] })

        post '/analyze?content=def+f%3A+pass&path=test.py', 'invalid-json', 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['summary']).to be_a(Hash)
      end
    end
  end

  describe 'POST /diff' do
    context 'when missing required params' do
      it 'returns 400' do
        post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json = JSON.parse(last_response.body)
        expect(json['error']).to match(/Missing/)
      end
    end

    context 'with valid payload' do
      it 'returns diff and new code review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
          .and_return({ 'changes' => 1 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'b'))
          .and_return({ 'score' => 88 })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['diff']).to eq({ 'changes' => 1 })
        expect(json['new_code_review']).to eq({ 'score' => 88 })
      end
    end
  end

  describe 'POST /metrics' do
    context 'when content missing' do
      it 'returns 400' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json = JSON.parse(last_response.body)
        expect(json['error']).to eq('Missing content')
      end
    end

    context 'when valid content provided' do
      it 'returns metrics, review, and computed overall quality' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'x'))
          .and_return({ 'complexity' => 1 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'x'))
          .and_return({ 'score' => 85, 'issues' => ['i1'] })

        post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['metrics']).to eq({ 'complexity' => 1 })
        expect(json['review']).to eq({ 'score' => 85, 'issues' => ['i1'] })
        expect(json['overall_quality']).to eq(25.0)
      end
    end

    context 'when downstream returns error' do
      it 'returns overall_quality as 0.0' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'error' => 'timeout' })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({ 'score' => 90, 'issues' => [] })

        post '/metrics', { content: 'y' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['overall_quality']).to eq(0.0)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when files array missing' do
      it 'returns 400' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json = JSON.parse(last_response.body)
        expect(json['error']).to eq('Missing files array')
      end
    end

    context 'with valid files' do
      it 'returns statistics and computed health score' do
        files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }]
        expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/statistics', hash_including(files: files))
          .and_return({ 'total_files' => 10, 'total_lines' => 1000, 'languages' => { 'ruby' => 10 } })
        expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/statistics', hash_including(files: files))
          .and_return({ 'average_score' => 90, 'total_issues' => 20, 'average_complexity' => 0.5 })

        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['file_statistics']['total_files']).to eq(10)
        expect(json['review_statistics']['average_score']).to eq(90)
        expect(json['summary']['health_score']).to eq(71.0)
        expect(json['timestamp']).to be_a(String)
        expect(json['timestamp']).to match(/\d{4}-\d{2}-\d{2}T/)
      end
    end

    context 'when computed health score is negative' do
      it 'clamps to 0.0' do
        files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }]
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'total_files' => 1, 'total_lines' => 10, 'languages' => { 'ruby' => 1 } })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({ 'average_score' => 10, 'total_issues' => 50, 'average_complexity' => 2.0 })

        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['summary']['health_score']).to eq(0.0)
      end
    end
  end

  describe 'GET /traces' do
    it 'returns total traces and list' do
      traces = [{ 'id' => 'a' }, { 'id' => 'b' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)
      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    context 'when no traces found' do
      it 'returns 404' do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return([])
        get '/traces/xyz'
        expect(last_response.status).to eq(404)
        json = JSON.parse(last_response.body)
        expect(json['error']).to eq('No traces found for correlation ID')
      end
    end

    context 'when traces exist' do
      it 'returns traces for the given correlation id' do
        traces = [{ 'step' => 1 }, { 'step' => 2 }]
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return(traces)
        get '/traces/abc'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['correlation_id']).to eq('abc')
        expect(json['trace_count']).to eq(2)
        expect(json['traces']).to eq(traces)
      end
    end
  end

  describe 'Validation errors endpoints' do
    describe 'GET /validation/errors' do
      it 'returns list of validation errors' do
        errors = [{ 'field' => 'content', 'message' => 'missing' }]
        allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)
        get '/validation/errors'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['total_errors']).to eq(1)
        expect(json['errors']).to eq(errors)
      end
    end

    describe 'DELETE /validation/errors' do
      it 'clears validation errors' do
        expect(RequestValidator).to receive(:clear_validation_errors)
        delete '/validation/errors'
        expect(last_response.status).to eq(200)
        json = JSON.parse(last_response.body)
        expect(json['message']).to eq('Validation errors cleared')
      end
    end
  end
end
