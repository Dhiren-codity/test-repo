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
    context 'when dependent services are healthy and unhealthy' do
      it 'returns aggregated statuses' do
        allow(HTTParty).to receive(:get) do |url, opts|
          if url == 'http://localhost:8080/health' && opts == { timeout: 2 }
            double(code: 200)
          elsif url == 'http://localhost:8081/health' && opts == { timeout: 2 }
            double(code: 500)
          else
            double(code: 404)
          end
        end

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']).to include('ruby', 'go', 'python')
        expect(body['services']['ruby']['status']).to eq('healthy')
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('unhealthy')
      end
    end

    context 'when a service is unreachable' do
      it 'marks it as unreachable with error' do
        allow(HTTParty).to receive(:get) do |url, _opts|
          raise Net::OpenTimeout.new('execution expired') if url == 'http://localhost:8080/health'

          double(code: 200)
        end

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('unreachable')
        expect(body['services']['go']).to have_key('error')
      end
    end
  end

  describe 'POST /diff' do
    context 'when required fields are missing' do
      it 'returns 400 with error message' do
        post '/diff', { old_content: 'old only' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'with valid old and new content' do
      it 'returns diff and review of new content' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', { old_content: 'old text', new_content: 'new text' })
          .and_return({ 'changes' => 2 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', { content: 'new text' })
          .and_return({ 'score' => 90, 'issues' => [] })

        post '/diff', { old_content: 'old text', new_content: 'new text' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['diff']).to eq({ 'changes' => 2 })
        expect(body['new_code_review']).to eq({ 'score' => 90, 'issues' => [] })
      end
    end
  end

  describe 'POST /metrics' do
    context 'when content is missing' do
      it 'returns 400 with error message' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing content')
      end
    end

    context 'with valid content' do
      it 'returns metrics, review, and computed overall quality score' do
        metrics = { 'complexity' => 1 }
        review = { 'score' => 80, 'issues' => [] }

        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', { content: 'code here' })
          .and_return(metrics)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', { content: 'code here' })
          .and_return(review)

        post '/metrics', { content: 'code here' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['metrics']).to eq(metrics)
        expect(body['review']).to eq(review)
        expect(body['overall_quality']).to eq(70.0)
      end

      it 'returns 0.0 for overall quality when services return error' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', { content: 'code here' })
          .and_return({ 'error' => 'timeout' })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', { content: 'code here' })
          .and_return({ 'score' => 90, 'issues' => [] })

        post '/metrics', { content: 'code here' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['overall_quality']).to eq(0.0)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when files array is missing' do
      it 'returns 400 with error' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing files array')
      end
    end

    context 'with valid files' do
      it 'returns aggregated statistics and health score' do
        files = [
          { 'path' => 'a.rb', 'content' => 'puts 1' },
          { 'path' => 'b.py', 'content' => 'print(1)' }
        ]

        file_stats = { 'total_files' => 2, 'total_lines' => 10, 'languages' => { 'ruby' => 1, 'python' => 1 } }
        review_stats = { 'average_score' => 90.0, 'total_issues' => 1, 'average_complexity' => 0.1 }

        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/statistics', { files: files })
          .and_return(file_stats)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/statistics', { files: files })
          .and_return(review_stats)

        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['file_statistics']).to eq(file_stats)
        expect(body['review_statistics']).to eq(review_stats)
        expect(body['summary']['total_files']).to eq(2)
        expect(body['summary']['total_lines']).to eq(10)
        expect(body['summary']['languages']).to eq(file_stats['languages'])
        expect(body['summary']['average_quality_score']).to eq(90.0)
        expect(body['summary']['total_issues']).to eq(1)
        expect(body['summary']['health_score']).to eq(86.0)
        expect(body['timestamp']).to be_a(String)
      end
    end
  end

  describe 'GET /traces' do
    it 'returns all traces' do
      traces = [
        { 'id' => '1', 'path' => '/analyze' },
        { 'id' => '2', 'path' => '/metrics' }
      ]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    context 'when no traces exist for the id' do
      it 'returns 404 with error' do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

        get '/traces/abc'
        expect(last_response.status).to eq(404)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('No traces found for correlation ID')
      end
    end

    context 'when traces exist for the id' do
      it 'returns trace details' do
        traces = [{ 'step' => 'start' }, { 'step' => 'finish' }]
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(traces)

        get '/traces/xyz'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['correlation_id']).to eq('xyz')
        expect(body['trace_count']).to eq(2)
        expect(body['traces']).to eq(traces)
      end
    end
  end

  describe 'validation errors management' do
    describe 'GET /validation/errors' do
      it 'returns current validation errors' do
        errors = [{ 'field' => 'content', 'message' => 'required' }]
        allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

        get '/validation/errors'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['total_errors']).to eq(1)
        expect(body['errors']).to eq(errors)
      end
    end

    describe 'DELETE /validation/errors' do
      it 'clears validation errors' do
        expect(RequestValidator).to receive(:clear_validation_errors)

        delete '/validation/errors'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['message']).to eq('Validation errors cleared')
      end
    end
  end
end
