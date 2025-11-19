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
    let(:go_health_url) { "#{app.settings.go_service_url}/health" }
    let(:py_health_url) { "#{app.settings.python_service_url}/health" }

    context 'when all services are healthy' do
      before do
        allow(HTTParty).to receive(:get).with(go_health_url, timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with(py_health_url, timeout: 2).and_return(double(code: 200))
      end

      it 'returns healthy statuses for all services' do
        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['ruby']['status']).to eq('healthy')
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a service is unhealthy or unreachable' do
      before do
        allow(HTTParty).to receive(:get).with(go_health_url, timeout: 2).and_return(double(code: 500))
        allow(HTTParty).to receive(:get).with(py_health_url,
                                              timeout: 2).and_raise(StandardError.new('connection refused'))
      end

      it 'marks go as unhealthy and python as unreachable' do
        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('unhealthy')
        expect(body['services']['python']['status']).to eq('unreachable')
        expect(body['services']['python']).to have_key('error')
      end
    end
  end

  describe 'POST /analyze (validation failures)' do
    let(:error_obj) { double(to_hash: { field: 'content', message: 'is required' }) }

    before do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])
    end

    it 'returns 422 with validation details' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to eq([{ 'field' => 'content', 'message' => 'is required' }])
    end
  end

  describe 'POST /diff' do
    context 'when required params are missing' do
      it 'returns 400 for missing content' do
        post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'with valid params' do
      let(:diff_result) { { 'changes' => 3, 'diff' => '@@ -1,2 +1,2 @@' } }
      let(:review_result) { { 'score' => 90, 'issues' => [] } }

      before do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'old', new_content: 'new'), anything)
          .and_return(diff_result)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'new'), anything)
          .and_return(review_result)
      end

      it 'returns diff and new code review' do
        post '/diff', { old_content: 'old', new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['diff']).to eq(diff_result)
        expect(body['new_code_review']).to eq(review_result)
      end
    end
  end

  describe 'POST /metrics' do
    context 'when content is missing' do
      it 'returns 400' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing content')
      end
    end

    context 'with valid content' do
      let(:metrics) { { 'complexity' => 1 } }
      let(:review) { { 'score' => 90, 'issues' => [{}] } }

      before do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'code'), anything)
          .and_return(metrics)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'code'), anything)
          .and_return(review)
      end

      it 'returns metrics, review, and overall_quality' do
        post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['metrics']).to eq(metrics)
        expect(body['review']).to eq(review)
        # expected overall_quality = (0.9 - 0.1 - 0.5) * 100 = 30.0
        expect(body['overall_quality']).to eq(30.0)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when files array is missing' do
      it 'returns 400' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing files array')
      end
    end

    context 'with valid files data' do
      let(:files) { [{ 'path' => 'a.py', 'content' => 'print()' }] }
      let(:file_stats) do
        {
          'total_files' => 1,
          'total_lines' => 10,
          'languages' => { 'python' => 1 }
        }
      end
      let(:review_stats) do
        {
          'average_score' => 80.0,
          'total_issues' => 2,
          'average_complexity' => 0.1
        }
      end

      before do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/statistics', hash_including(files: files), anything)
          .and_return(file_stats)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/statistics', hash_including(files: files), anything)
          .and_return(review_stats)
      end

      it 'returns dashboard summary with computed health score' do
        post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body).to have_key('timestamp')
        expect(body['file_statistics']).to eq(file_stats)
        expect(body['review_statistics']).to eq(review_stats)
        summary = body['summary']
        expect(summary['total_files']).to eq(1)
        expect(summary['total_lines']).to eq(10)
        expect(summary['languages']).to eq({ 'python' => 1 })
        # health_score = 80 - (2/1)*2 - (0.1*30) = 80 - 4 - 3 = 73.0
        expect(summary['health_score']).to eq(73.0)
      end
    end
  end

  describe 'GET /traces' do
    let(:traces) { [{ 'id' => 1 }, { 'id' => 2 }] }

    before do
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)
    end

    it 'returns all traces with total count' do
      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    context 'when traces are not found' do
      before do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])
      end

      it 'returns 404' do
        get '/traces/abc'
        expect(last_response.status).to eq(404)
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('No traces found for correlation ID')
      end
    end

    context 'when traces are found' do
      let(:found_traces) { [{ 'step' => 'a' }, { 'step' => 'b' }] }

      before do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(found_traces)
      end

      it 'returns trace info' do
        get '/traces/xyz'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['correlation_id']).to eq('xyz')
        expect(body['trace_count']).to eq(2)
        expect(body['traces']).to eq(found_traces)
      end
    end
  end

  describe 'Validation errors management endpoints' do
    describe 'GET /validation/errors' do
      before do
        allow(RequestValidator).to receive(:get_validation_errors).and_return([{ 'field' => 'x' }])
      end

      it 'returns current validation errors' do
        get '/validation/errors'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['total_errors']).to eq(1)
        expect(body['errors']).to eq([{ 'field' => 'x' }])
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

  describe 'private helper methods' do
    let(:instance) { app.new }

    describe '#detect_language' do
      it 'detects python from .py extension' do
        expect(instance.send(:detect_language, 'file.py')).to eq('python')
      end

      it 'detects ruby from .rb extension' do
        expect(instance.send(:detect_language, 'script.rb')).to eq('ruby')
      end

      it 'returns unknown for unrecognized extension' do
        expect(instance.send(:detect_language, 'README.txt')).to eq('unknown')
      end

      it 'handles uppercase extensions' do
        expect(instance.send(:detect_language, 'MAIN.GO')).to eq('go')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics is nil' do
        expect(instance.send(:calculate_quality_score, nil, { 'score' => 80 })).to eq(0.0)
      end

      it 'returns 0.0 when either has error' do
        expect(instance.send(:calculate_quality_score, { 'error' => 'x' }, { 'score' => 80 })).to eq(0.0)
      end

      it 'calculates score with penalties and rounding' do
        metrics = { 'complexity' => 2 }
        review = { 'score' => 85, 'issues' => [{}] }
        # base 0.85, penalty 0.2 + 0.5 = 0.7 => 0.15 * 100 = 15.0
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(15.0)
      end

      it 'clamps score to 0 when negative' do
        metrics = { 'complexity' => 5 }
        review = { 'score' => 50, 'issues' => [{}, {}, {}, {}] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(0)
      end

      it 'returns review score when no penalties' do
        metrics = { 'complexity' => 0 }
        review = { 'score' => 75, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(75.0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when inputs have errors' do
        file_stats = { 'error' => 'oops' }
        review_stats = { 'average_score' => 90 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(0.0)
      end

      it 'calculates health score with penalties' do
        file_stats = { 'total_files' => 4 }
        review_stats = { 'average_score' => 90, 'total_issues' => 6,
                         'average_complexity' => 0.2 }
        # issue_penalty = (6/4)*2 = 3, complexity_penalty = 6 => 90 - 9 = 81.0
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(81.0)
      end

      it 'clamps to 0 minimum' do
        file_stats = { 'total_files' => 1 }
        review_stats = { 'average_score' => 10,
                         'total_issues' => 20, 'average_complexity' => 1.0 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(0)
      end

      it 'clamps to 100 maximum' do
        file_stats = { 'total_files' => 10 }
        review_stats = { 'average_score' => 100,
                         'total_issues' => 0, 'average_complexity' => 0 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(100.0)
      end
    end
  end
end
