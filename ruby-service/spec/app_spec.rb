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

    context 'when validation fails' do
      it 'returns 422 with details' do
        allow(RequestValidator).to receive(:validate_analyze_request)
          .and_return([double(to_hash: { field: 'content', message: 'is required' })])
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({}) # should not be called, but stub to be safe
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({})

        post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(422)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Validation failed')
        expect(json_response['details']).to be_an(Array)
        expect(json_response['details'].first['field']).to eq('content')
      end
    end

    context 'when correlation id is present' do
      it 'forwards correlation id to downstream services and returns it' do
        expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/parse', hash_including(content: 'puts 1', path: 'file.rb'), kind_of(String))
          .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
        expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'puts 1', language: 'ruby'), kind_of(String))
          .and_return({ 'score' => 95, 'issues' => [] })

        post '/analyze', { content: 'puts 1', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['correlation_id']).to be_a(String)
        expect(json_response['correlation_id'].length).to be > 0
      end
    end
  end

  describe 'GET /status' do
    it 'aggregates service health statuses' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with(PolyglotAPI.settings.go_service_url)
        .and_return({ 'status' => 'healthy' })
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .with(PolyglotAPI.settings.python_service_url)
        .and_return({ 'status' => 'unreachable' })

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('unreachable')
    end
  end

  describe 'POST /diff' do
    context 'when parameters are missing' do
      it 'returns 400 when old_content is missing' do
        post '/diff', { new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to match(/Missing/)
      end

      it 'returns 400 when new_content is missing' do
        post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to match(/Missing/)
      end
    end

    context 'when parameters are valid' do
      it 'returns diff and new code review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'a', new_content: 'b'), nil)
          .and_return({ 'changes' => 1 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'b'), nil)
          .and_return({ 'score' => 88, 'issues' => [] })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['diff']).to eq({ 'changes' => 1 })
        expect(json_response['new_code_review']['score']).to eq(88)
      end
    end
  end

  describe 'POST /metrics' do
    context 'when content is missing' do
      it 'returns 400' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to match(/Missing content/)
      end
    end

    context 'when content is provided' do
      it 'returns metrics, review, and overall quality' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'code'), nil)
          .and_return({ 'complexity' => 2 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'code'), nil)
          .and_return({ 'score' => 80, 'issues' => [1] })
        allow_any_instance_of(PolyglotAPI).to receive(:calculate_quality_score)
          .and_return(73.25)

        post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['metrics']).to include('complexity' => 2)
        expect(json_response['review']).to include('score' => 80)
        expect(json_response['overall_quality']).to eq(73.25)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when files param is missing or empty' do
      it 'returns 400' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to match(/Missing files array/)
      end
    end

    context 'when files are provided' do
      let(:files) do
        [
          { 'path' => 'a.rb', 'content' => 'puts 1' },
          { 'path' => 'b.py', 'content' => 'print(1)' }
        ]
      end

      it 'returns aggregated statistics and summary' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/statistics', hash_including(files: files), nil)
          .and_return({ 'total_files' => 2, 'total_lines' => 3, 'languages' => { 'ruby' => 1, 'python' => 1 } })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/statistics', hash_including(files: files), nil)
          .and_return({ 'average_score' => 85.5, 'total_issues' => 1, 'average_complexity' => 0.1 })
        allow_any_instance_of(PolyglotAPI).to receive(:calculate_dashboard_health_score)
          .and_return(66.6)

        fake_time = double(iso8601: '2020-01-01T00:00:00Z')
        allow(Time).to receive(:now).and_return(fake_time)

        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['timestamp']).to eq('2020-01-01T00:00:00Z')
        expect(json_response['file_statistics']['total_files']).to eq(2)
        expect(json_response['review_statistics']['average_score']).to eq(85.5)
        expect(json_response['summary']['health_score']).to eq(66.6)
        expect(json_response['summary']['languages']).to eq({ 'ruby' => 1, 'python' => 1 })
      end
    end
  end

  describe 'GET /traces' do
    it 'returns all traces' do
      allow(CorrelationIdMiddleware).to receive(:all_traces)
        .and_return([{ 'id' => '1' }, { 'id' => '2' }])

      get '/traces'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['total_traces']).to eq(2)
      expect(json_response['traces'].length).to eq(2)
    end
  end

  describe 'GET /traces/:correlation_id' do
    context 'when traces exist' do
      it 'returns traces for the given correlation id' do
        allow(CorrelationIdMiddleware).to receive(:get_traces)
          .with('abc-123')
          .and_return([{ 'event' => 'start' }, { 'event' => 'end' }])

        get '/traces/abc-123'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['correlation_id']).to eq('abc-123')
        expect(json_response['trace_count']).to eq(2)
      end
    end

    context 'when traces do not exist' do
      it 'returns 404' do
        allow(CorrelationIdMiddleware).to receive(:get_traces)
          .with('missing')
          .and_return([])

        get '/traces/missing'
        expect(last_response.status).to eq(404)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to match(/No traces/)
      end
    end
  end

  describe 'validation errors endpoints' do
    describe 'GET /validation/errors' do
      it 'returns total errors and list' do
        allow(RequestValidator).to receive(:get_validation_errors)
          .and_return([{ 'field' => 'content', 'message' => 'bad' }])

        get '/validation/errors'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['total_errors']).to eq(1)
        expect(json_response['errors'].first['field']).to eq('content')
      end
    end

    describe 'DELETE /validation/errors' do
      it 'clears errors and returns confirmation' do
        expect(RequestValidator).to receive(:clear_validation_errors)

        delete '/validation/errors'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['message']).to eq('Validation errors cleared')
      end
    end
  end

  describe 'private helpers' do
    let(:instance) do
      PolyglotAPI.new
    end

    describe '#detect_language' do
      it 'detects known extensions' do
        expect(instance.send(:detect_language, 'main.go')).to eq('go')
        expect(instance.send(:detect_language, 'script.py')).to eq('python')
        expect(instance.send(:detect_language, 'app.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'index.js')).to eq('javascript')
        expect(instance.send(:detect_language, 'app.ts')).to eq('typescript')
        expect(instance.send(:detect_language, 'Main.java')).to eq('java')
      end

      it 'returns unknown for unsupported extensions' do
        expect(instance.send(:detect_language, 'README.md')).to eq('unknown')
        expect(instance.send(:detect_language, '')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics or review are missing or erroneous' do
        expect(instance.send(:calculate_quality_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_quality_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_quality_score, { 'error' => 'x' }, {})).to eq(0.0)
        expect(instance.send(:calculate_quality_score, {}, { 'error' => 'y' })).to eq(0.0)
      end

      it 'calculates score with penalties and clamps to 0..100' do
        metrics = { 'complexity' => 3 }
        review = { 'score' => 120, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(100)

        metrics2 = { 'complexity' => 5 }
        review2 = { 'score' => 50, 'issues' => [1, 2, 3] }
        result = instance.send(:calculate_quality_score, metrics2, review2)
        expect(result).to be_between(0, 100).inclusive
        expect(result).to eq(0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when stats are missing or erroneous' do
        expect(instance.send(:calculate_dashboard_health_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, { 'error' => 'x' }, {})).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, {}, { 'error' => 'y' })).to eq(0.0)
      end

      it 'calculates health score with penalties and clamps within bounds' do
        file_stats = { 'total_files' => 5 }
        review_stats = { 'average_score' => 90, 'total_issues' => 10, 'average_complexity' => 0.1 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(83.0)

        review_stats_high = { 'average_score' => 150, 'total_issues' => 0, 'average_complexity' => 0 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats_high)).to eq(100)
      end
    end

    describe '#check_service_health' do
      it 'returns healthy when service responds 200' do
        response = double(code: 200)
        expect(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.go_service_url}/health",
                                               timeout: 2).and_return(response)
        result = instance.send(:check_service_health, PolyglotAPI.settings.go_service_url)
        expect(result).to eq({ status: 'healthy' })
      end

      it 'returns unhealthy when non-200' do
        response = double(code: 500)
        expect(HTTParty).to receive(:get).with("#{PolyglotAPI.settings.go_service_url}/health",
                                               timeout: 2).and_return(response)
        result = instance.send(:check_service_health, PolyglotAPI.settings.go_service_url)
        expect(result).to eq({ status: 'unhealthy' })
      end

      it 'returns unreachable on exceptions' do
        expect(HTTParty).to receive(:get).and_raise(StandardError.new('timeout'))
        result = instance.send(:check_service_health, PolyglotAPI.settings.go_service_url)
        expect(result[:status]).to eq('unreachable')
        expect(result[:error]).to match(/timeout/)
      end
    end

    describe '#call_go_service' do
      it 'parses JSON response body' do
        response = double(body: { 'ok' => true }.to_json)
        expect(HTTParty).to receive(:post).with(
          "#{PolyglotAPI.settings.go_service_url}/parse",
          hash_including(body: '{}', headers: hash_including('Content-Type' => 'application/json'), timeout: 5)
        ).and_return(response)
        result = instance.send(:call_go_service, '/parse', {})
        expect(result).to eq({ 'ok' => true })
      end

      it 'includes correlation id header when provided' do
        response = double(body: '{}')
        expect(HTTParty).to receive(:post).with(
          "#{PolyglotAPI.settings.go_service_url}/parse",
          hash_including(headers: hash_including(CorrelationIdMiddleware::CORRELATION_ID_HEADER => 'cid-1'))
        ).and_return(response)
        instance.send(:call_go_service, '/parse', {}, 'cid-1')
      end

      it 'returns error hash on exception' do
        expect(HTTParty).to receive(:post).and_raise(StandardError.new('boom'))
        result = instance.send(:call_go_service, '/parse', {})
        expect(result['error']).to match(/boom/)
      end
    end

    describe '#call_python_service' do
      it 'parses JSON response body' do
        response = double(body: { 'ok' => true }.to_json)
        expect(HTTParty).to receive(:post).with(
          "#{PolyglotAPI.settings.python_service_url}/review",
          hash_including(body: '{}', headers: hash_including('Content-Type' => 'application/json'), timeout: 5)
        ).and_return(response)
        result = instance.send(:call_python_service, '/review', {})
        expect(result).to eq({ 'ok' => true })
      end

      it 'includes correlation id header when provided' do
        response = double(body: '{}')
        expect(HTTParty).to receive(:post).with(
          "#{PolyglotAPI.settings.python_service_url}/review",
          hash_including(headers: hash_including(CorrelationIdMiddleware::CORRELATION_ID_HEADER => 'cid-2'))
        ).and_return(response)
        instance.send(:call_python_service, '/review', {}, 'cid-2')
      end

      it 'returns error hash on exception' do
        expect(HTTParty).to receive(:post).and_raise(StandardError.new('error'))
        result = instance.send(:call_python_service, '/review', {})
        expect(result['error']).to match(/error/)
      end
    end
  end
end
