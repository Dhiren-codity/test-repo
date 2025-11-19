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

  describe 'GET /status' do
    context 'when downstream services are healthy' do
      it 'reports healthy statuses' do
        allow(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.go_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.python_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))

        get '/status'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['ruby']['status']).to eq('healthy')
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a service is unreachable' do
      it 'reports unreachable with error' do
        allow(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.go_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.python_service_url}/health",
                                              timeout: 2).and_raise(StandardError.new('timeout'))

        get '/status'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('unreachable')
        expect(json_response['services']['python']['error']).to include('timeout')
      end
    end
  end

  describe 'POST /analyze validations' do
    it 'returns 422 with validation errors' do
      error_double = double(to_hash: { field: 'content', message: 'required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_double])

      post '/analyze', { content: '', path: '' }.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(422)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Validation failed')
      expect(json_response['details']).to be_an(Array)
      expect(json_response['details'].first['field']).to eq('content')
    end

    it 'propagates correlation id to downstream services' do
      cid = 'cid-123'
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', kind_of(Hash), cid)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', kind_of(Hash), cid)
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json',
                                                                       CorrelationIdMiddleware::CORRELATION_ID_HEADER => cid

      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['correlation_id']).to eq(cid)
    end

    it 'falls back to params when JSON body is invalid' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).and_return({ 'language' => 'python',
                                                                                   'lines' => %w[a b] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).and_return({ 'score' => 75, 'issues' => [] })

      post '/analyze?content=print(1)&path=a.py', 'not-json', 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']['language']).to eq('python')
    end

    it 'detects language from path and passes to python service' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).and_return({ 'language' => 'ruby',
                                                                                   'lines' => ['puts x'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts x'), anything)
        .and_return({ 'score' => 88, 'issues' => [] })

      post '/analyze', { content: 'puts x', path: 'hello.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'

      expect(last_response.status).to eq(200)
    end
  end

  describe 'POST /diff' do
    context 'when missing parameters' do
      it 'returns 400 for missing old_content' do
        post '/diff', { new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Missing old_content or new_content')
      end

      it 'returns 400 for missing new_content' do
        post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'when valid' do
      it 'returns diff and new code review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).and_return({ 'diff' => ['-a', '+b'] })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).and_return({ 'score' => 92,
                                                                                         'issues' => [] })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['diff']).to eq({ 'diff' => ['-a', '+b'] })
        expect(json_response['new_code_review']).to eq({ 'score' => 92, 'issues' => [] })
      end
    end
  end

  describe 'POST /metrics' do
    context 'when missing content' do
      it 'returns 400' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Missing content')
      end
    end

    context 'when valid and computes overall quality' do
      it 'calculates score using metrics and review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).and_return({ 'complexity' => 2 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).and_return({ 'score' => 80,
                                                                                         'issues' => %w[a b] })

        post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['metrics']).to eq({ 'complexity' => 2 })
        expect(json_response['review']).to eq({ 'score' => 80, 'issues' => %w[a b] })
        expect(json_response['overall_quality']).to eq(0)
      end
    end

    context 'when go metrics call fails' do
      it 'returns error in metrics and overall_quality is 0.0' do
        allow(HTTParty).to receive(:post) do |url, _options|
          raise StandardError.new('timeout') if url == "#{PolyglotAPI.settings.go_service_url}/metrics"

          double(body: { score: 85, issues: [] }.to_json)
        end

        post '/metrics', { content: 'xyz' }.to_json, 'CONTENT_TYPE' => 'application/json'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['metrics']).to include('error')
        expect(json_response['overall_quality']).to eq(0.0)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when missing files' do
      it 'returns 400' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Missing files array')
      end
    end

    context 'when valid' do
      it 'returns statistics and summary with computed health score' do
        allow(Time).to receive(:now).and_return(Time.parse('2020-01-01T12:00:00Z'))
        file_stats = {
          'total_files' => 2,
          'total_lines' => 100,
          'languages' => { 'ruby' => 1, 'python' => 1 }
        }
        review_stats = {
          'average_score' => 90.0,
          'total_issues' => 4,
          'average_complexity' => 0.5
        }
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service).with('/statistics',
                                                                             kind_of(Hash)).and_return(file_stats)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service).with('/statistics',
                                                                                 kind_of(Hash)).and_return(review_stats)

        post '/dashboard', { files: [{ path: 'a.rb' }, { path: 'b.py' }] }.to_json, 'CONTENT_TYPE' => 'application/json'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['timestamp']).to eq('2020-01-01T12:00:00Z')
        expect(json_response['file_statistics']).to eq(file_stats)
        expect(json_response['review_statistics']).to eq(review_stats)
        expect(json_response['summary']['total_files']).to eq(2)
        expect(json_response['summary']['total_lines']).to eq(100)
        expect(json_response['summary']['languages']).to eq({ 'ruby' => 1, 'python' => 1 })
        expect(json_response['summary']['average_quality_score']).to eq(90.0)
        expect(json_response['summary']['total_issues']).to eq(4)
        expect(json_response['summary']['health_score']).to eq(71.0)
      end
    end
  end

  describe 'GET /traces' do
    it 'returns all traces' do
      traces = [
        { id: 'cid1', path: '/analyze' },
        { id: 'cid2', path: '/metrics' }
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
    context 'when not found' do
      it 'returns 404' do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('missing').and_return([])

        get '/traces/missing'

        expect(last_response.status).to eq(404)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('No traces found for correlation ID')
      end
    end

    context 'when found' do
      it 'returns traces for the specific correlation id' do
        traces = [{ step: 'start' }, { step: 'end' }]
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('cid-xyz').and_return(traces)

        get '/traces/cid-xyz'

        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['correlation_id']).to eq('cid-xyz')
        expect(json_response['trace_count']).to eq(2)
        expect(json_response['traces']).to eq(traces)
      end
    end
  end

  describe 'GET /validation/errors' do
    it 'returns validation errors collection' do
      errors = [{ field: 'content', message: 'required' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'

      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['total_errors']).to eq(1)
      expect(json_response['errors']).to eq(errors)
    end
  end

  describe 'DELETE /validation/errors' do
    it 'clears validation errors and returns confirmation' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'

      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['message']).to eq('Validation errors cleared')
    end
  end
end
